"""Canonical historical-data ingestion boundary.

Adapters normalize raw CSV/JSON/vendor payloads into QuantX historical
observations without fabricating missing values or market metadata. Optional
market-calendar classification is preserved with each observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Mapping, Protocol

from .calendar import MarketCalendar, SessionClassification
from .data import HistoricalDataSeries, HistoricalObservation


@dataclass(frozen=True, slots=True)
class RawMarketRecord:
    """Minimal source record supplied by an ingestion adapter."""

    timestamp: datetime
    instrument: str
    sequence: int
    fields: Mapping[str, object]


class HistoricalDataSource(Protocol):
    def read(self) -> Iterable[RawMarketRecord]: ...


class HistoricalNormalizer(Protocol):
    """Map source records to the canonical observation representation."""

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation: ...


@dataclass(frozen=True, slots=True)
class CanonicalOHLCVNormalizer:
    """Strict normalizer for sources that provide OHLCV fields."""

    dataset_id: str
    dataset_version: str
    calendar: MarketCalendar | None = None

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation:
        if record.timestamp.tzinfo is None or record.timestamp.utcoffset() is None:
            raise ValueError("historical timestamp must be timezone-aware")

        required = ("open", "high", "low", "close")
        missing = [name for name in required if name not in record.fields]
        if missing:
            raise ValueError(f"missing required historical fields: {', '.join(missing)}")

        values = {name: Decimal(str(record.fields[name])) for name in required}
        volume = None
        if "volume" in record.fields and record.fields["volume"] is not None:
            volume = Decimal(str(record.fields["volume"]))

        session: SessionClassification | None = None
        if self.calendar is not None:
            session = self.calendar.classify(record.timestamp)

        data: dict[str, object] = {**values, "volume": volume}
        if session is not None:
            data.update(
                {
                    "session_status": session.status.value,
                    "session_timezone": session.timezone,
                    "calendar_version": session.calendar_version,
                    "session_reason": session.reason,
                }
            )

        return HistoricalObservation(
            timestamp=record.timestamp,
            instrument=record.instrument,
            sequence=record.sequence,
            data=data,
            source_id=self.dataset_id,
            dataset_version=self.dataset_version,
        )


def ingest_source(
    source: HistoricalDataSource,
    normalizer: HistoricalNormalizer,
) -> HistoricalDataSeries:
    """Normalize source records and preserve deterministic source ordering."""

    observations = tuple(normalizer.normalize(record) for record in source.read())
    return HistoricalDataSeries(observations)
