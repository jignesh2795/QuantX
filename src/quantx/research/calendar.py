"""Market-session and calendar primitives for point-in-time research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, tzinfo
from enum import StrEnum


class SessionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AUCTION = "AUCTION"
    HALT = "HALT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A timezone-aware tradable/session window."""

    open_at: datetime
    close_at: datetime
    status: SessionStatus = SessionStatus.OPEN

    def __post_init__(self) -> None:
        if self.open_at.tzinfo is None or self.open_at.utcoffset() is None:
            raise ValueError("open_at must be timezone-aware")
        if self.close_at.tzinfo is None or self.close_at.utcoffset() is None:
            raise ValueError("close_at must be timezone-aware")
        if self.close_at <= self.open_at:
            raise ValueError("close_at must be after open_at")


class MarketCalendar:
    """Calendar interface used by normalization/replay without hard-coding a market."""

    def session_for(self, timestamp: datetime) -> SessionWindow | None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FixedDailySessionCalendar(MarketCalendar):
    """Small deterministic calendar useful for tests and simple venues.

    Production exchanges should provide dedicated market plugins with holidays,
    auctions, halts, early closes, expiry rules, and historical calendar versions.
    """

    timezone: tzinfo
    open_time: time
    close_time: time

    def session_for(self, timestamp: datetime) -> SessionWindow | None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        local = timestamp.astimezone(self.timezone)
        if local.weekday() >= 5:
            return None
        start = datetime.combine(local.date(), self.open_time, self.timezone)
        end = datetime.combine(local.date(), self.close_time, self.timezone)
        if not (start <= local <= end):
            return None
        return SessionWindow(start, end)
