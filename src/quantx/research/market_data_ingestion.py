"""Canonical historical candle ingestion bridge.

This module connects the vendor-neutral ``MarketDataPort`` to the
vendor-neutral ``MarketDataStore``: retrieve canonical candles once, persist
them once, and return the store's inserted-row count.

There is deliberately no normalization, scheduling, retry, batching,
caching, pagination, or network behavior here. Duplicate and conflict
semantics belong to the store; timestamp and range validation fail fast
before either boundary is touched.
"""

from __future__ import annotations

from datetime import datetime

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.ports.market_data import MarketDataPort, MarketDataStore


def ingest_historical_candles(
    *,
    market_data: MarketDataPort,
    store: MarketDataStore,
    instrument: InstrumentId,
    timeframe: str,
    start: datetime,
    end: datetime,
    source_id: str,
    dataset_version: str = "",
) -> int:
    """Retrieve one candle collection and persist it unchanged.

    Returns the store's inserted-row count. An empty upstream collection
    persists nothing and returns zero without fabricating data.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end < start:
        raise ValueError("ingestion end must not precede start")
    if not timeframe.strip():
        raise ValueError("timeframe must not be empty")
    if not source_id.strip():
        raise ValueError("source_id must not be empty")
    candles = tuple(market_data.candles(instrument, timeframe=timeframe, start=start, end=end))
    _assert_canonical(candles)
    return store.save_candles(candles, source_id=source_id, dataset_version=dataset_version)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"ingestion {name} must be timezone-aware")


def _assert_canonical(candles: tuple[Candle, ...]) -> None:
    for candle in candles:
        if not isinstance(candle, Candle):
            raise ValueError("upstream market data must be canonical candles")


__all__ = ["ingest_historical_candles"]
