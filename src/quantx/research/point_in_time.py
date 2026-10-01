"""Unified point-in-time research context resolution.

A historical timestamp is usable for trading research only after both venue
session state and instrument/contract state have been resolved from versioned
sources. Current metadata must never be used as a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .calendar import MarketCalendar, SessionClassification, SessionStatus
from .market_rules import (
    PointInTimeInstrumentRegistry,
    PointInTimeTradability,
    TradabilityStatus,
    resolve_tradability,
)


@dataclass(frozen=True, slots=True)
class PointInTimeContext:
    instrument_id: str
    timestamp: datetime
    session: SessionClassification
    instrument: PointInTimeTradability

    @property
    def executable(self) -> bool:
        return (
            self.session.status is SessionStatus.OPEN
            and self.instrument.status is TradabilityStatus.TRADABLE
        )

    @property
    def execution_block_reason(self) -> str | None:
        if self.session.status is not SessionStatus.OPEN:
            return f"market session is {self.session.status.value}"
        if self.instrument.status is not TradabilityStatus.TRADABLE:
            return f"instrument status is {self.instrument.status.value}"
        return None


class PointInTimeContextResolver:
    """Resolve the complete historical trading context for one observation."""

    def __init__(
        self,
        *,
        calendar: MarketCalendar,
        instrument_registry: PointInTimeInstrumentRegistry,
    ) -> None:
        self._calendar = calendar
        self._instrument_registry = instrument_registry

    def resolve(self, instrument_id: str, timestamp: datetime) -> PointInTimeContext:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        session = self._calendar.classify(timestamp)
        instrument = resolve_tradability(self._instrument_registry, instrument_id, timestamp)
        return PointInTimeContext(
            instrument_id=instrument_id,
            timestamp=timestamp,
            session=session,
            instrument=instrument,
        )
