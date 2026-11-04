"""Compatibility re-exports for market calendars.

``HistoricalCalendar`` remains defined here as the research-facing
protocol. The moved market calendar contracts are re-exported from
``quantx.markets.common.calendar``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from quantx.markets.common.calendar import (
    FixedDailySessionCalendar,
    MarketCalendar,
    SessionClassification,
    SessionStatus,
)

__all__ = [
    "FixedDailySessionCalendar",
    "HistoricalCalendar",
    "MarketCalendar",
    "SessionClassification",
    "SessionStatus",
]


class HistoricalCalendar(Protocol):
    """Calendar contract used by historical quality checks.

    None means the calendar cannot establish whether a historical bar should
    exist at the timestamp. Implementations must not infer missing coverage.
    """

    version: str

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None: ...
