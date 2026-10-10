from contextlib import contextmanager
from types import SimpleNamespace

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
    first = DurableTradingGate(store)
    second = DurableTradingGate(store)
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
