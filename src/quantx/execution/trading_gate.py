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
        """Atomically authorize a submission and hold the gate through the call."""
        with self._lock:
            if not self._state.enabled:
                yield False
                return
            yield True

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
    """Trading gate whose block/enable state survives process restart."""

    is_durable = True

    def __init__(
        self,
        state_store: TradingGateStateStore,
        *,
        default_enabled: bool = True,
    ) -> None:
        self._state_store = state_store
        persisted = state_store.load()
        initial = persisted or TradingGateState(enabled=default_enabled)
        super().__init__(enabled=initial.enabled)
        with self._lock:
            self._state = initial
        if persisted is None:
            state_store.save(initial)

    def state(self) -> TradingGateState:
        persisted = self._state_store.load()
        if persisted is None:
            with self._lock:
                return TradingGateState(
                    enabled=False,
                    reason="durable trading-gate state is unavailable",
                )
        with self._lock:
            self._state = persisted
            return persisted

    def allow(self) -> bool:
        return self.state().enabled

    @contextmanager
    def submission_permit(self) -> Iterator[bool]:
        """Refresh durable state, then hold the gate through broker submission."""
        with self._lock:
            with self._state_store.synchronize():
                persisted = self._state_store.load()
                if persisted is None:
                    yield False
                    return
                self._state = persisted
                if not persisted.enabled:
                    yield False
                    return
                yield True

    def block(self, reason: str) -> TradingGateState:
        reason = reason.strip()
        if not reason:
            raise ValueError("kill-switch reason must not be empty")
        state = TradingGateState(enabled=False, reason=reason)
        with self._lock:
            self._state_store.save(state)
            self._state = state
            return state

    def enable(self) -> TradingGateState:
        state = TradingGateState(enabled=True)
        with self._lock:
            self._state_store.save(state)
            self._state = state
            return state
