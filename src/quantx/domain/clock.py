"""Clock abstractions used by live execution and deterministic simulation.

QuantumTrade already had a Clock/SystemClock/SimulatedClock boundary. QuantX
keeps that capability in the domain so replay, paper, and live execution share
one time contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class Clock(ABC):
    """Port for obtaining time without coupling the domain to wall-clock APIs."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""
        raise NotImplementedError


class SystemClock(Clock):
    """Production clock backed by the system UTC clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock(Clock):
    """Deterministic fixed clock retained for existing QuantX tests."""

    def __init__(self, current: datetime) -> None:
        self._current = _as_utc(current)

    def now(self) -> datetime:
        return self._current

    def set(self, current: datetime) -> None:
        self._current = _as_utc(current)


class SimulatedClock(Clock):
    """Controllable monotonic clock for replay, paper, and backtesting."""

    def __init__(self, initial_time: datetime) -> None:
        self._current = _as_utc(initial_time)

    def now(self) -> datetime:
        return self._current

    def set_time(self, timestamp: datetime) -> None:
        timestamp = _as_utc(timestamp)
        if timestamp < self._current:
            raise ValueError("simulated time cannot move backwards")
        self._current = timestamp

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("simulated time cannot move backwards")
        self._current += delta


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = ["Clock", "FixedClock", "SimulatedClock", "SystemClock"]
