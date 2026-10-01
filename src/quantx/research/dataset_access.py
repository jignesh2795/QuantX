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

from datetime import datetime

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.ports.market_data import MarketDataStore

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


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset read {name} must be timezone-aware")


__all__ = ["read_candles"]
