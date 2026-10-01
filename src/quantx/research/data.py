"""Point-in-time historical market-data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator

from quantx.domain.market_data import Quote
from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    snapshot: MarketSnapshot
    source_id: str
    dataset_version: str
    sequence: int

    @property
    def timestamp(self) -> datetime:
        return self.snapshot.timestamp

    @property
    def instrument(self) -> InstrumentId:
        return self.snapshot.instrument

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must not be empty")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")


class HistoricalDataSeries:
    def __init__(self, observations: Iterable[HistoricalObservation]) -> None:
        values = tuple(observations)
        if not values:
            raise ValueError("historical data series requires observations")
        instrument = values[0].snapshot.instrument
        if any(value.snapshot.instrument != instrument for value in values):
            raise ValueError("all observations must use the same instrument")
        self._observations = tuple(
            sorted(values, key=lambda item: (item.snapshot.timestamp, item.sequence))
        )
        self.instrument = instrument

    def __iter__(self) -> Iterator[HistoricalObservation]:
        return iter(self._observations)

    def __len__(self) -> int:
        return len(self._observations)

    def as_tuple(self) -> tuple[HistoricalObservation, ...]:
        return self._observations

    def as_of(self, timestamp: datetime) -> tuple[HistoricalObservation, ...]:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return tuple(item for item in self._observations if item.snapshot.timestamp <= timestamp)

    def between(self, start: datetime, end: datetime) -> tuple[HistoricalObservation, ...]:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("end must be timezone-aware")
        if end < start:
            raise ValueError("end must not precede start")
        return tuple(
            item
            for item in self._observations
            if start <= item.snapshot.timestamp <= end
        )

    def latest_at_or_before(self, timestamp: datetime) -> HistoricalObservation | None:
        values = self.as_of(timestamp)
        return values[-1] if values else None
