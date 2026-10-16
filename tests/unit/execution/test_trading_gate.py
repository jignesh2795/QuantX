from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.execution.trading_gate import (
    DurableTradingGate,
    InMemoryTradingGateStateStore,
    TradingGate,
    TradingGateState,
)


def _paper_request() -> object:
    return SimpleNamespace(
        execution_context=SimpleNamespace(execution_mode="paper"),
    )


class _UnavailableStateStore:
    """State store whose durable state can never be loaded."""

    def load(self) -> TradingGateState | None:
        return None

    def save(self, state: TradingGateState) -> None:
        return None

    @contextmanager
    def synchronize(self):
        yield


def test_gate_blocks_and_reports_reason() -> None:
    gate = TradingGate()
    state = gate.block("operator emergency stop")

    assert state.enabled is False
    assert state.reason == "operator emergency stop"
    assert gate.allow() is False

    gate.enable()
    assert gate.allow() is True
    assert gate.state().reason == ""


def test_orchestrator_fails_closed_before_adapter_submission() -> None:
    gate = TradingGate()
    gate.block("risk limit reached")
    called = False

    class Adapter:
        def execute(self, request, *, snapshot):
            nonlocal called
            called = True
            raise AssertionError("adapter must not be called")

    result = ExecutionOrchestrator(
        paper_executor=Adapter(),
        trading_gate=gate,
    ).execute(_paper_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "trading is blocked: risk limit reached"
    assert called is False


def test_empty_kill_switch_reason_is_rejected() -> None:
    gate = TradingGate()

    try:
        gate.block(" ")
    except ValueError as exc:
        assert str(exc) == "kill-switch reason must not be empty"
    else:
        raise AssertionError("expected ValueError")


def test_durable_gate_state_survives_gate_recreation() -> None:
    store = InMemoryTradingGateStateStore()
    first = DurableTradingGate(store)
    first.block("operator emergency stop")

    second = DurableTradingGate(store)

    assert second.allow() is False
    assert second.state() == TradingGateState(False, "operator emergency stop")


def test_durable_gate_refreshes_state_across_existing_instances() -> None:
    store = InMemoryTradingGateStateStore()
    first = DurableTradingGate(store)
    second = DurableTradingGate(store)

    first.block("operator emergency stop")

    assert second.allow() is False
    assert second.state() == TradingGateState(False, "operator emergency stop")


def test_durable_gate_shared_store_serializes_submission_permit() -> None:
    from threading import Event, Thread

    store = InMemoryTradingGateStateStore()
    first = DurableTradingGate(store, default_enabled=True)
    second = DurableTradingGate(store, default_enabled=True)
    entered = Event()
    release = Event()
    blocked = Event()

    def protected_submission() -> None:
        with first.submission_permit() as permitted:
            assert permitted is True
            entered.set()
            assert release.wait(timeout=5)

    def block_gate() -> None:
        second.block("operator emergency stop")
        blocked.set()

    submit_thread = Thread(target=protected_submission)
    block_thread = Thread(target=block_gate)
    submit_thread.start()
    assert entered.wait(timeout=5)

    block_thread.start()
    assert not blocked.wait(timeout=0.1)

    release.set()
    submit_thread.join(timeout=5)
    block_thread.join(timeout=5)

    assert not submit_thread.is_alive()
    assert not block_thread.is_alive()
    assert second.allow() is False
    assert second.state() == TradingGateState(False, "operator emergency stop")


def test_durable_gate_missing_state_fails_closed() -> None:
    """Unavailable durable state must never become an implicit approval."""
    gate = DurableTradingGate(_UnavailableStateStore())

    assert gate.allow() is False
    assert gate.state() == TradingGateState(
        enabled=False,
        reason="durable trading-gate state is unavailable",
    )


def test_durable_gate_permit_fails_closed_when_state_unavailable() -> None:
    """A submission permit must be refused when durable state cannot be loaded."""
    gate = DurableTradingGate(_UnavailableStateStore())

    with gate.submission_permit() as permitted:
        assert permitted is False


class _FailWhenDisablingStateStore(InMemoryTradingGateStateStore):
    """Persist enabled state but simulate a durable block-write failure."""

    def save(self, state: TradingGateState) -> None:
        if not state.enabled:
            raise OSError("cannot persist disabled gate state")
        super().save(state)


def test_durable_gate_defaults_to_disarmed_without_persisted_state() -> None:
    store = InMemoryTradingGateStateStore()

    gate = DurableTradingGate(store)

    assert gate.allow() is False
    assert gate.state() == TradingGateState(enabled=False, reason="")
    assert store.load() == TradingGateState(enabled=False, reason="")


def test_durable_gate_stays_blocked_when_persisting_block_raises() -> None:
    store = _FailWhenDisablingStateStore()
    gate = DurableTradingGate(store, default_enabled=True)

    with pytest.raises(OSError, match="cannot persist disabled gate state"):
        gate.block("operator emergency stop")

    assert gate.allow() is False
    with gate.submission_permit() as permitted:
        assert permitted is False


class _StaleEnabledStateStore(InMemoryTradingGateStateStore):
    """Keeps reporting enabled after a failed write, like a stale replica."""

    def __init__(self) -> None:
        super().__init__()
        super().save(TradingGateState(enabled=True, reason=""))

    def save(self, state: TradingGateState) -> None:
        raise OSError("cannot persist gate state")


def test_durable_gate_failed_block_latch_ignores_stale_enabled_store() -> None:
    """A latched block fault must never reload stale enabled state."""
    store = _StaleEnabledStateStore()
    gate = DurableTradingGate(store, default_enabled=True)
    assert gate.allow() is True

    with pytest.raises(OSError, match="cannot persist gate state"):
        gate.block("operator emergency stop")

    for _ in range(3):
        assert gate.allow() is False
        assert gate.state() == TradingGateState(False, "operator emergency stop")
        with gate.submission_permit() as permitted:
            assert permitted is False
        assert gate.admit_submission() is False
    assert store.load() == TradingGateState(enabled=True, reason="")


class _ToggleableStateStore(InMemoryTradingGateStateStore):
    """Deterministic store whose writes can be failed on demand."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_saves = False

    def save(self, state: TradingGateState) -> None:
        if self.fail_saves:
            raise OSError("cannot persist gate state")
        super().save(state)


def test_durable_gate_failed_enable_leaves_gate_blocked() -> None:
    """Permission requires a successfully persisted enable."""
    store = _ToggleableStateStore()
    gate = DurableTradingGate(store)
    assert gate.allow() is False

    store.fail_saves = True
    with pytest.raises(OSError, match="cannot persist gate state"):
        gate.enable()

    assert gate.allow() is False
    assert gate.state() == TradingGateState(
        enabled=False, reason="durable trading-gate enable failed to persist"
    )
    with gate.submission_permit() as permitted:
        assert permitted is False
    assert gate.admit_submission() is False


def test_durable_gate_successful_enable_clears_latched_fault() -> None:
    """An explicit enable persisted successfully recovers a latched fault."""
    store = _ToggleableStateStore()
    gate = DurableTradingGate(store)

    store.fail_saves = True
    with pytest.raises(OSError, match="cannot persist gate state"):
        gate.block("operator emergency stop")
    assert gate.allow() is False

    store.fail_saves = False
    state = gate.enable()
    assert state == TradingGateState(enabled=True, reason="")
    assert gate.allow() is True
    with gate.submission_permit() as permitted:
        assert permitted is True
    assert gate.admit_submission() is True


class _LoadRaisingStateStore(InMemoryTradingGateStateStore):
    """Store whose reads always fail while writes succeed."""

    def load(self) -> TradingGateState | None:
        raise OSError("cannot read gate state")


def test_durable_gate_unreadable_store_fails_closed_without_raising() -> None:
    """Query paths fail closed when a store operation raises."""
    gate = DurableTradingGate(_LoadRaisingStateStore())

    assert gate.allow() is False
    assert gate.state() == TradingGateState(
        enabled=False, reason="durable trading-gate state is unavailable"
    )
    with gate.submission_permit() as permitted:
        assert permitted is False
    assert gate.admit_submission() is False


class _LoadGatedStateStore(InMemoryTradingGateStateStore):
    """Store whose reads wait on an event once gating is armed.

    Gating stays off during construction so setup never stalls; arm it
    together with save failures to interleave a read with a failed block.
    """

    def __init__(self, *, load_entered, load_release) -> None:
        super().__init__()
        self.fail_saves = False
        self.gate_loads = False
        self._load_entered = load_entered
        self._load_release = load_release

    def load(self) -> TradingGateState | None:
        if self.gate_loads:
            self._load_entered.set()
            assert self._load_release.wait(timeout=10)
        return super().load()

    def save(self, state: TradingGateState) -> None:
        if self.fail_saves:
            raise OSError("cannot persist gate state")
        super().save(state)


def test_durable_gate_concurrent_read_linearizes_against_failed_block() -> None:
    """A read that starts before a failed block sees pre-block state, while
    the failed block waits for that brief in-flight store read (never for
    broker I/O, of which none is involved here). Later reads stay blocked.

    The ``not block_done`` assertion pins the serialization: it fails if
    ``block()`` completes while a store read is still in flight, which would
    let that read miss the latched fault and reload stale enabled state."""
    from threading import Event, Thread

    load_entered = Event()
    load_release = Event()
    block_done = Event()
    store = _LoadGatedStateStore(load_entered=load_entered, load_release=load_release)
    gate = DurableTradingGate(store, default_enabled=True)
    store.fail_saves = True
    store.gate_loads = True
    outcome: dict = {}

    def read_allow() -> None:
        try:
            outcome["allow"] = gate.allow()
        except BaseException as exc:
            outcome["error"] = exc

    def fail_block() -> None:
        try:
            gate.block("operator emergency stop")
        except OSError:
            outcome["block_raised"] = True
        finally:
            block_done.set()

    reader = Thread(target=read_allow)
    reader.start()
    try:
        assert load_entered.wait(timeout=10)
        blocker = Thread(target=fail_block)
        blocker.start()
        try:
            assert not block_done.wait(timeout=0.5)
            load_release.set()
            blocker.join(timeout=10)
            reader.join(timeout=10)
        finally:
            load_release.set()
            blocker.join(timeout=10)
    finally:
        load_release.set()
        reader.join(timeout=10)
    assert not reader.is_alive()
    assert "error" not in outcome
    assert outcome.get("block_raised") is True
    assert outcome.get("allow") is True
    assert gate.allow() is False
    assert gate.state() == TradingGateState(False, "operator emergency stop")


def _assert_gate_denied(gate: DurableTradingGate, reason: str) -> None:
    assert gate.allow() is False
    assert gate.state() == TradingGateState(False, reason)
    with gate.submission_permit() as permitted:
        assert permitted is False
    assert gate.admit_submission() is False


def test_shared_store_failed_block_denies_second_gate() -> None:
    """A failed block latches the shared domain: every gate on the store is
    denied even while the store keeps reporting stale enabled state."""
    store = _FailWhenDisablingStateStore()
    first = DurableTradingGate(store, default_enabled=True)
    second = DurableTradingGate(store)
    assert first.allow() is True
    assert second.allow() is True

    with pytest.raises(OSError, match="cannot persist disabled gate state"):
        first.block("operator emergency stop")

    _assert_gate_denied(first, "operator emergency stop")
    _assert_gate_denied(second, "operator emergency stop")
    assert store.load() == TradingGateState(enabled=True, reason="")

    late = DurableTradingGate(store)
    _assert_gate_denied(late, "operator emergency stop")


def test_shared_store_failed_enable_denies_both_gates_until_recovery() -> None:
    """A failed enable latches the shared domain; only a successfully
    persisted enable, on either gate, recovers permission."""
    store = _ToggleableStateStore()
    first = DurableTradingGate(store, default_enabled=True)
    second = DurableTradingGate(store)
    assert first.allow() is True
    assert second.allow() is True

    store.fail_saves = True
    with pytest.raises(OSError, match="cannot persist gate state"):
        first.enable()
    _assert_gate_denied(first, "durable trading-gate enable failed to persist")
    _assert_gate_denied(second, "durable trading-gate enable failed to persist")

    store.fail_saves = False
    assert second.enable() == TradingGateState(enabled=True, reason="")
    assert first.allow() is True
    assert second.allow() is True


def test_independent_stores_do_not_share_faults() -> None:
    """A fault latched on one store must never affect an unrelated store."""
    failing = _ToggleableStateStore()
    first = DurableTradingGate(failing, default_enabled=True)
    second = DurableTradingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    assert first.allow() is True
    assert second.allow() is True

    failing.fail_saves = True
    with pytest.raises(OSError, match="cannot persist gate state"):
        first.block("operator emergency stop")

    _assert_gate_denied(first, "operator emergency stop")
    assert second.allow() is True
    with second.submission_permit() as permitted:
        assert permitted is True
    assert second.admit_submission() is True
