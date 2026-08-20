"""Clock abstractions used by live execution and deterministic simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone


class Clock(ABC):
    """Port for obtaining time without coupling the domain to wall-clock APIs."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class SystemClock(Clock):
    """Production clock backed by the system UTC clock."""

    def now(self) -> datetime:
        """Return the current UTC timestamp."""
        return datetime.now(timezone.utc)


class FixedClock(Clock):
    """Deterministic clock useful for tests and reproducible simulation."""

    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._current = current.astimezone(timezone.utc)

    def now(self) -> datetime:
        """Return the current fixed timestamp."""
        return self._current

    def set(self, current: datetime) -> None:
        """Replace the fixed timestamp."""
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._current = current.astimezone(timezone.utc)
