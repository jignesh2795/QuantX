"""Market-session classification for historical research and replay.

Calendars are deliberately separate from normalization so venue-specific
session rules can be supplied by plugins without leaking into the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo


class SessionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AUCTION = "AUCTION"
    HALT = "HALT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SessionClassification:
    timestamp: datetime
    status: SessionStatus
    timezone: str
    calendar_version: str
    reason: str = ""


class MarketCalendar:
    """Protocol-like base for market calendar implementations."""

    version: str

    def classify(self, timestamp: datetime) -> SessionClassification:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FixedDailySessionCalendar(MarketCalendar):
    """Deterministic development calendar with one daily open interval."""

    timezone: str
    open_time: time
    close_time: time
    version: str = "fixed-daily-v1"

    def classify(self, timestamp: datetime) -> SessionClassification:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        local = timestamp.astimezone(ZoneInfo(self.timezone))
        current = local.timetz().replace(tzinfo=None)
        status = SessionStatus.OPEN if self.open_time <= current < self.close_time else SessionStatus.CLOSED
        return SessionClassification(
            timestamp=timestamp,
            status=status,
            timezone=self.timezone,
            calendar_version=self.version,
            reason="within configured session" if status is SessionStatus.OPEN else "outside configured session",
        )
