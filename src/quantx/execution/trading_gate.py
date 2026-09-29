"""Runtime trading gate for fail-closed order submission control."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class TradingGateState:
    enabled: bool
    reason: str = ""


class TradingGate:
    """Process-local kill switch for new order execution.

    The gate does not cancel, reconcile, or mutate existing orders. It only
    answers whether a new execution request may be submitted.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._lock = RLock()
        self._state = TradingGateState(enabled=enabled)

    def state(self) -> TradingGateState:
        with self._lock:
            return self._state

    def allow(self) -> bool:
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
