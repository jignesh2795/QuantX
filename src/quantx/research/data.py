"""Point-in-time historical market-data contracts.

A historical observation preserves one canonical market-data payload
unchanged: either a quote snapshot (``Quote``/``MarketSnapshot``) or a
canonical ``Candle``. Candle-backed observations keep the complete OHLCV
payload without projecting it onto a quote, so no OHLCV information is lost
between dataset reads, series assembly, and replay.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId

HistoricalSnapshot = Quote | Candle
"""Vendor-neutral research payload: a quote snapshot or a canonical candle."""


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    snapshot: HistoricalSnapshot
    source_id: str
    dataset_version: str
    sequence: int
    dataset_id: str | None = None

    @property
    def timestamp(self) -> datetime:
        return self.snapshot.timestamp

    @property
    def instrument(self) -> InstrumentId:
        return self.snapshot.instrument

    @classmethod
    def from_candle(
        cls,
        candle: Candle,
        source_id: str,
        dataset_version: str,
        sequence: int,
        dataset_id: str | None = None,
    ) -> HistoricalObservation:
        """Wrap a canonical candle without converting or copying it.

        The exact ``Candle`` instance is preserved as the observation
        snapshot: no quote projection, no synthetic bid/ask fields, and no
        OHLCV re-encoding. The canonical ``Candle`` remains responsible for
        its own validation.
        """
        if not isinstance(candle, Candle):
            raise TypeError("candle observations require a canonical Candle")
        return HistoricalObservation(
            snapshot=candle,
            source_id=source_id,
            dataset_version=dataset_version,
            sequence=sequence,
            dataset_id=dataset_id,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, (Quote, Candle)):
            raise TypeError("snapshot must be a canonical Quote or Candle")
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must not be empty")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        if self.dataset_id is not None and not self.dataset_id.strip():
            raise ValueError("dataset_id must not be empty")


class HistoricalDataSeries:
    def __init__(self, observations: Iterable[HistoricalObservation]) -> None:
        values = tuple(observations)
        if not values:
            raise ValueError("historical data series requires observations")
        instrument = values[0].instrument
        if any(value.instrument != instrument for value in values):
            raise ValueError("all observations must use the same instrument")
        self._observations = tuple(sorted(values, key=lambda item: (item.timestamp, item.sequence)))
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
        return tuple(item for item in self._observations if item.timestamp <= timestamp)

    def between(self, start: datetime, end: datetime) -> tuple[HistoricalObservation, ...]:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("end must be timezone-aware")
        if end < start:
            raise ValueError("end must not precede start")
        return tuple(item for item in self._observations if start <= item.timestamp <= end)

    def latest_at_or_before(self, timestamp: datetime) -> HistoricalObservation | None:
        values = self.as_of(timestamp)
        return values[-1] if values else None
