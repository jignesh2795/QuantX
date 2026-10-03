"""Dataset-backed historical research access seam.

This module resolves one declared dataset version through the dataset
catalog and reads the corresponding canonical candles from the market-data
store. The catalog is the sole authority for the
``(dataset_id, version) -> source_id + dataset identity`` relationship, so
callers never supply a source identity of their own.

This is a read boundary only. It performs no source verification, no
backtesting, no simulation, and no integrity checking; those remain with
the artifact verifier, the research runner, and the provenance record.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.ports.market_data import MarketDataStore

from .data import HistoricalObservation
from .dataset_catalog import DatasetCatalog


def read_candles(
    *,
    catalog: DatasetCatalog,
    store: MarketDataStore,
    dataset_id: str,
    version: str,
    instrument: InstrumentId,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> tuple[Candle, ...]:
    """Read canonical candles for one registered dataset version unchanged.

    A dataset that was never registered raises explicitly instead of
    falling back to an unscoped store query. A registered dataset with no
    candles in range returns the store's empty tuple without fabrication.
    Catalog and store failures propagate unchanged.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end < start:
        raise ValueError("dataset read end must not precede start")
    if not timeframe.strip():
        raise ValueError("timeframe must not be empty")
    registered = catalog.get(dataset_id, version)
    if registered is None:
        raise ValueError(f"dataset is not registered: {dataset_id} {version}")
    identity = registered.identity
    return store.get_candles(
        instrument,
        timeframe=timeframe,
        start=start,
        end=end,
        source_id=identity.source_id,
        dataset_version=identity.version,
    )


def candles_to_observations(
    candles: Iterable[Candle],
    *,
    source_id: str,
    dataset_version: str,
    start_sequence: int = 0,
) -> tuple[HistoricalObservation, ...]:
    """Wrap canonical candles as lossless historical observations.

    Each candle is preserved exactly via
    ``HistoricalObservation.from_candle`` with no quote projection, no
    OHLCV re-encoding, and no synthetic bid/ask fields. Sequences assign
    deterministically from ``start_sequence`` in iteration order; the
    research series remains responsible for chronological ordering.
    """
    if not source_id.strip():
        raise ValueError("source_id must not be empty")
    if not dataset_version.strip():
        raise ValueError("dataset_version must not be empty")
    if start_sequence < 0:
        raise ValueError("sequence must not be negative")
    return tuple(
        HistoricalObservation.from_candle(
            candle,
            source_id,
            dataset_version,
            start_sequence + index,
        )
        for index, candle in enumerate(tuple(candles))
    )


def read_observations(
    *,
    catalog: DatasetCatalog,
    store: MarketDataStore,
    dataset_id: str,
    version: str,
    instrument: InstrumentId,
    timeframe: str,
    start: datetime,
    end: datetime,
    start_sequence: int = 0,
) -> tuple[HistoricalObservation, ...]:
    """Read one registered dataset version as lossless candle observations.

    This resolves the ``(dataset_id, version) -> source_id + dataset
    identity`` relationship through the catalog exactly like
    ``read_candles`` (which performs the version/source-scoped store read),
    then wraps the returned canonical candles without projecting them to
    quotes. Catalog and store failures propagate unchanged. This performs
    no source verification, no backtesting, no simulation, and no integrity
    checking.
    """
    candles = read_candles(
        catalog=catalog,
        store=store,
        dataset_id=dataset_id,
        version=version,
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end,
    )
    registered = catalog.get(dataset_id, version)
    if registered is None:  # pragma: no cover - read_candles already raised
        raise ValueError(f"dataset is not registered: {dataset_id} {version}")
    identity = registered.identity
    return candles_to_observations(
        candles,
        source_id=identity.source_id,
        dataset_version=identity.version,
        start_sequence=start_sequence,
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset read {name} must be timezone-aware")


__all__ = ["candles_to_observations", "read_candles", "read_observations"]
