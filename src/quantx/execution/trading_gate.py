"""Runtime trading gates for fail-closed order submission control."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TradingGateState:
    enabled: bool
    reason: str = ""


class TradingGateStateStore(Protocol):
    """Durable state boundary for a trading gate."""

    def load(self) -> TradingGateState | None: ...

    def save(self, state: TradingGateState) -> None: ...

    def synchronize(self) -> AbstractContextManager[None]: ...


class InMemoryTradingGateStateStore:
    """Process-local state store useful for deterministic tests and simulations."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state: TradingGateState | None = None

    def load(self) -> TradingGateState | None:
        with self._lock:
            return self._state

    def save(self, state: TradingGateState) -> None:
        with self._lock:
            self._state = state

    @contextmanager
    def synchronize(self) -> Iterator[None]:
        """Serialize gate submissions and state changes sharing this store."""
        with self._lock:
            yield


class TradingGate:
    """Process-local kill switch for new order execution.

    The gate does not cancel, reconcile, or mutate existing orders. It only
    answers whether a new execution request may be submitted.
    """

    is_durable = False

    def __init__(self, *, enabled: bool = True) -> None:
        self._lock = RLock()
        self._state = TradingGateState(enabled=enabled)

    def state(self) -> TradingGateState:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        with self._lock:
            return self._state.enabled

    @contextmanager
    def submission_permit(self) -> Iterator[bool]:
        """Authorize a submission and hold the gate through reservation creation.

        The permit covers the gate check plus idempotency reservation only.
        It is released before any broker I/O, so ``block()`` never waits for
        a slow broker call. Callers must re-check submit admission at the
        :meth:`admit_submission` boundary immediately before broker contact.
        """
        with self._lock:
            if not self._state.enabled:
                yield False
                return
            yield True

    def admit_submission(self) -> bool:
        """Linearization point for submit admission: one atomic enabled check.

        A submission that has not crossed this boundary when ``block()``
        returns must not proceed. A submission that already crossed it is
        in-flight and is never reversed by a later ``block()``. This check
        holds no lock across broker I/O.
        """
        with self._lock:
            return self._state.enabled

    def block(self, reason: str) -> TradingGateState:
        reason = reason.strip()
        if not reason:
            raise ValueError("kill-switch reason must not be empty")
        with self._lock:
            self._state = TradingGateState(enabled=False, reason=reason)
            return self._state

    def enable(self) -> TradingGateState:
        with self._lock:
            self._state = TradingGateState(enabled=True)
            return self._state


class DurableTradingGate(TradingGate):
    """Trading gate whose block/enable state survives process restart.

    A missing durable state defaults to disarmed (``default_enabled=False``);
    the default is persisted, and an initialization persistence failure never
    leaves an armed gate behind. A failed persist of ``block()`` or
    ``enable()`` latches a process-local fail-closed fault that preserves the
    intended reason: while latched, ``allow()``, ``state()``, and submit
    admission report blocked without reloading possibly stale enabled state
    from the store. A later successfully persisted ``block()`` or ``enable()``
    replaces the latch. Query paths (``allow()``, ``state()``, permits,
    admission) fail closed when durable state is missing, unavailable, or
    unreadable, including when a store operation raises; command paths
    (``block()``, ``enable()``) still surface persistence errors loudly.

    Durability limitation: the fault latch is process-local. A failed write
    cannot by itself persist evidence that the write failed, so a process
    crash loses the latch. Only successfully persisted state (for example a
    disarmed default) survives restart; failed-write recovery always requires
    a subsequent successful persist, typically an explicit operator enable.
    """

    is_durable = True

    def __init__(
        self,
        state_store: TradingGateStateStore,
        *,
        default_enabled: bool = False,
    ) -> None:
        self._state_store = state_store
        self._fault: TradingGateState | None = None
        try:
            persisted = state_store.load()
        except Exception:
            persisted = None
        initial = persisted if persisted is not None else TradingGateState(enabled=default_enabled)
        super().__init__(enabled=initial.enabled)
        with self._lock:
            self._state = initial
        if persisted is None:
            try:
                state_store.save(initial)
            except Exception:
                fault = TradingGateState(
                    enabled=False,
                    reason="durable trading-gate initialization failed",
                )
                with self._lock:
                    self._state = fault
                    self._fault = fault
                raise

    def state(self) -> TradingGateState:
        # The lock is held across the store read so a failed persist that
        # latches a fault is never missed by a concurrent read: every state
        # observation linearizes against command writes. Reads are brief
        # local store operations; no broker I/O ever holds this lock.
        with self._lock:
            if self._fault is not None:
                return self._fault
            try:
                persisted = self._state_store.load()
            except Exception:
                persisted = None
            if persisted is None:
                return TradingGateState(
                    enabled=False,
                    reason="durable trading-gate state is unavailable",
                )
            self._state = persisted
            return persisted

    def allow(self) -> bool:
        return self.state().enabled

    def _refresh_decision_under_store_lock(self) -> bool:
        """Refresh durable state and decide admission.

        Requires ``self._lock`` and the store ``synchronize()`` context to be
        held by the caller. Observes the fault latch first and never consults
        the store while a fault is latched, so a failed persist can never be
        undone by reloading stale enabled state.
        """
        if self._fault is not None:
            return False
        try:
            persisted = self._state_store.load()
        except Exception:
            return False
        if persisted is None:
            return False
        self._state = persisted
        return persisted.enabled

    @contextmanager
    def submission_permit(self) -> Iterator[bool]:
        """Refresh durable state, then hold the gate through reservation only.

        The permit covers the gate check plus idempotency reservation. It is
        released before any broker I/O, so ``block()`` never waits for a slow
        broker call. Callers must re-check submit admission at the
        :meth:`admit_submission` boundary immediately before broker contact.
        """
        with self._lock:
            with self._state_store.synchronize():
                if not self._refresh_decision_under_store_lock():
                    yield False
                    return
                yield True

    def admit_submission(self) -> bool:
        """Linearization point for submit admission: one atomic durable check.

        Observes the fault latch first, then the durable store under the
        store lock. A submission that has not crossed this boundary when
        ``block()`` returns is denied here. A submission that already crossed
        it is in-flight and is never reversed by a later ``block()``. No lock
        is held across broker I/O.
        """
        with self._lock:
            with self._state_store.synchronize():
                return self._refresh_decision_under_store_lock()

    def block(self, reason: str) -> TradingGateState:
        reason = reason.strip()
        if not reason:
            raise ValueError("kill-switch reason must not be empty")
        state = TradingGateState(enabled=False, reason=reason)
        with self._lock:
            try:
                self._state_store.save(state)
            except Exception:
                # Latch blocked immediately: the operator asked for a block
                # and the durable write failed, so this process must never
                # reload stale enabled state and restore permission. The
                # error still propagates so the failure is visible.
                self._state = state
                self._fault = state
                raise
            self._state = state
            self._fault = None
            return state

    def enable(self) -> TradingGateState:
        state = TradingGateState(enabled=True)
        with self._lock:
            try:
                self._state_store.save(state)
            except Exception:
                # A failed enable leaves the gate blocked: permission requires
                # a successfully persisted enable, which also clears a
                # recoverable latched fault.
                fault = TradingGateState(
                    enabled=False,
                    reason="durable trading-gate enable failed to persist",
                )
                self._state = fault
                self._fault = fault
                raise
            self._state = state
            self._fault = None
            return state
