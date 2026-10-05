"""Market-session classification for historical research and replay.

Calendars are deliberately separate from normalization so venue-specific
session rules can be supplied by plugins without leaking into the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Protocol
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


class HistoricalCalendar(Protocol):
    """Calendar contract used by historical quality checks.

    None means the calendar cannot establish whether a historical bar should
    exist at the timestamp. Implementations must not infer missing coverage.
    """

    version: str

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None: ...


class MarketCalendar:
    """Protocol-like base for market calendar implementations."""

    version: str

    def classify(self, timestamp: datetime) -> SessionClassification:
        raise NotImplementedError

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None:
        """Return whether a historical bar is expected at the timestamp."""

        classification = self.classify(timestamp)
        if classification.status is SessionStatus.OPEN:
            return True
        if classification.status is SessionStatus.UNKNOWN:
            return None
        return False


@dataclass(frozen=True, slots=True)
class FixedDailySessionCalendar(MarketCalendar):
    """Deterministic development calendar with one daily open interval."""

    timezone: str
    open_time: time
    close_time: time
    version: str = "fixed-daily-v1"

    def __post_init__(self) -> None:
        if not self.timezone.strip():
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(self.timezone)
        except KeyError as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be before close_time")

    def classify(self, timestamp: datetime) -> SessionClassification:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        local = timestamp.astimezone(ZoneInfo(self.timezone))
        current = local.timetz().replace(tzinfo=None)
        if local.weekday() >= 5:
            status = SessionStatus.CLOSED
            reason = "outside configured session: weekend"
        else:
            status = (
                SessionStatus.OPEN
                if self.open_time <= current < self.close_time
                else SessionStatus.CLOSED
            )
            reason = (
                "within configured session"
                if status is SessionStatus.OPEN
                else "outside configured session"
            )
        return SessionClassification(
            timestamp=timestamp,
            status=status,
            timezone=self.timezone,
            calendar_version=self.version,
            reason=reason,
        )

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None:
        """Return whether a historical bar is expected in this fixed session."""

        classification = self.classify(timestamp)
        if classification.status is SessionStatus.OPEN:
            return True
        if classification.status is SessionStatus.UNKNOWN:
            return None
        return False


__all__ = [
    "FixedDailySessionCalendar",
    "HistoricalCalendar",
    "MarketCalendar",
    "SessionClassification",
    "SessionStatus",
]
