"""Deterministic orchestration for ingesting one registered historical dataset."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.ports.market_data import MarketDataPort, MarketDataStore

from .data_quality import HistoricalDataQuality, assess_candles
from .dataset_catalog import DatasetCatalog


@dataclass(frozen=True, slots=True)
class HistoricalDatasetIngestionResult:
    """Outcome of one bounded dataset ingestion operation."""

    dataset_id: str
    version: str
    source_id: str
    inserted_count: int
    quality: HistoricalDataQuality


class HistoricalDatasetIngestionService:
    """Compose catalog, market-data, quality, and storage boundaries once."""

    def __init__(
        self,
        *,
        catalog: DatasetCatalog,
        market_data: MarketDataPort,
        store: MarketDataStore,
    ) -> None:
        self._catalog = catalog
        self._market_data = market_data
        self._store = store

    def ingest(
        self,
        *,
        dataset_id: str,
        version: str,
        instrument: InstrumentId,
        timeframe: str,
        start: datetime,
        end: datetime,
        expected_timestamps: Iterable[datetime] | None = None,
    ) -> HistoricalDatasetIngestionResult:
        """Read, assess, and persist one registered dataset version."""
        _require_aware(start, "start")
        _require_aware(end, "end")
        if end < start:
            raise ValueError("dataset ingestion end must not precede start")
        if not timeframe.strip():
            raise ValueError("timeframe must not be empty")

        registered = self._catalog.get(dataset_id, version)
        if registered is None:
            raise ValueError(f"dataset is not registered: {dataset_id} {version}")

        candles = tuple(
            self._market_data.candles(
                instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        )
        _validate_candles(candles, instrument=instrument, timeframe=timeframe, start=start, end=end)
        quality = assess_candles(candles, expected_timestamps)
        inserted_count = self._store.save_candles(
            candles,
            source_id=registered.identity.source_id,
            dataset_version=registered.identity.version,
        )
        return HistoricalDatasetIngestionResult(
            dataset_id=registered.identity.dataset_id,
            version=registered.identity.version,
            source_id=registered.identity.source_id,
            inserted_count=inserted_count,
            quality=quality,
        )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset ingestion {name} must be timezone-aware")


def _validate_candles(
    candles: tuple[Candle, ...],
    *,
    instrument: InstrumentId,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> None:
    for candle in candles:
        if not isinstance(candle, Candle):
            raise ValueError("market data returned a non-canonical candle")
        if candle.instrument != instrument:
            raise ValueError("market data returned a candle for a different instrument")
        if candle.timeframe != timeframe:
            raise ValueError("market data returned a candle for a different timeframe")
        if candle.timestamp.tzinfo is None or candle.timestamp.utcoffset() is None:
            raise ValueError("market data candle timestamp must be timezone-aware")
        if not start <= candle.timestamp <= end:
            raise ValueError("market data returned a candle outside the requested range")


__all__ = [
    "HistoricalDatasetIngestionResult",
    "HistoricalDatasetIngestionService",
]
