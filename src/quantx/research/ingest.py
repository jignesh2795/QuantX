"""Canonical historical-data ingestion boundary.

Adapters normalize raw CSV/JSON/vendor payloads into QuantX historical
observations without fabricating missing values or market metadata. An
optional market calendar may be consulted during normalization.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId

from .calendar import MarketCalendar
from .data import HistoricalDataSeries, HistoricalObservation


@dataclass(frozen=True, slots=True)
class RawMarketRecord:
    """Minimal source record supplied by an ingestion adapter."""

    timestamp: datetime
    instrument: str
    sequence: int
    fields: Mapping[str, object]
    timeframe: str = field(kw_only=True)


class HistoricalDataSource(Protocol):
    def read(self) -> Iterable[RawMarketRecord]: ...


class HistoricalNormalizer(Protocol):
    """Map source records to the canonical observation representation."""

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation: ...


@dataclass(frozen=True, slots=True)
class CanonicalOHLCVNormalizer:
    """Strict normalizer that preserves OHLCV as a canonical Candle."""

    dataset_id: str
    dataset_version: str
    calendar: MarketCalendar | None = None

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation:
        if record.timestamp.tzinfo is None or record.timestamp.utcoffset() is None:
            raise ValueError("historical timestamp must be timezone-aware")

        required = ("open", "high", "low", "close", "volume")
        missing = [name for name in required if name not in record.fields]
        if missing:
            raise ValueError(f"missing required historical fields: {', '.join(missing)}")

        values = {
            name: Decimal(str(record.fields[name])) for name in ("open", "high", "low", "close")
        }
        volume = Decimal(str(record.fields["volume"]))

        if self.calendar is not None:
            self.calendar.classify(record.timestamp)

        instrument_id = InstrumentId("SOURCE", str(record.instrument))
        candle = Candle(
            instrument=instrument_id,
            timeframe=record.timeframe,
            timestamp=record.timestamp,
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            volume=volume,
        )
        return HistoricalObservation(
            snapshot=candle,
            source_id=self.dataset_id,
            dataset_version=self.dataset_version,
            sequence=record.sequence,
        )


@dataclass(frozen=True, slots=True)
class CatalogOHLCVNormalizer:
    """Normalize OHLCV records to catalog-resolved canonical identity."""

    registry: InstrumentRegistry
    instrument_id: InstrumentId
    dataset_id: str
    dataset_version: str
    calendar: MarketCalendar | None = None

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation:
        instrument = self.registry.resolve(self.instrument_id)
        if instrument is None:
            raise ValueError(f"unknown instrument: {self.instrument_id}")
        if record.instrument != instrument.symbol:
            raise ValueError(
                f"source symbol {record.instrument!r} does not match "
                f"instrument {instrument.symbol!r}"
            )

        observation = CanonicalOHLCVNormalizer(
            dataset_id=self.dataset_id,
            dataset_version=self.dataset_version,
            calendar=self.calendar,
        ).normalize(record)
        snapshot = observation.snapshot
        if not isinstance(snapshot, Candle):
            raise TypeError("historical OHLCV normalization must produce a Candle")

        canonical_snapshot = Candle(
            instrument=instrument.instrument_id,
            timeframe=snapshot.timeframe,
            timestamp=snapshot.timestamp,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
        )
        return HistoricalObservation(
            snapshot=canonical_snapshot,
            source_id=observation.source_id,
            dataset_version=observation.dataset_version,
            sequence=observation.sequence,
        )


def ingest_source(
    source: HistoricalDataSource,
    normalizer: HistoricalNormalizer,
) -> HistoricalDataSeries:
    """Normalize source records and preserve deterministic source ordering."""

    observations = tuple(normalizer.normalize(record) for record in source.read())
    return HistoricalDataSeries(observations)
