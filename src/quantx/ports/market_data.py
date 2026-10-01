"""Market-data adapter port."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId


@runtime_checkable
class MarketDataPort(Protocol):
    """Broker/vendor-neutral market-data interface."""

    def quote(self, instrument: InstrumentId) -> Quote | None:
        ...

    def candles(
        self,
        instrument: InstrumentId,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> Iterable[Candle]:
        ...

    def subscribe(self, instruments: Iterable[InstrumentId]) -> None:
        ...

    def unsubscribe(self, instruments: Iterable[InstrumentId]) -> None:
        ...


@runtime_checkable
class MarketDataStore(Protocol):
    """Vendor-neutral persistence boundary for canonical market observations.

    Implementations persist exact ``Quote``/``Candle`` values with their
    source identity. Retrieval is deterministic: exact instrument match,
    inclusive timestamp bounds, and chronological order. Implementations
    must never fabricate observations and must never silently overwrite
    stored content.
    """

    def save_candles(
        self,
        candles: Iterable[Candle],
        *,
        source_id: str,
        dataset_version: str = "",
    ) -> int:
        """Persist candles; return the number of newly stored rows."""
        ...

    def get_candles(
        self,
        instrument: InstrumentId,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        source_id: str | None = None,
        dataset_version: str | None = None,
    ) -> tuple[Candle, ...]:
        """Return stored candles for one instrument/timeframe in [start, end]."""
        ...

    def save_quotes(
        self,
        quotes: Iterable[Quote],
        *,
        source_id: str,
        dataset_version: str = "",
    ) -> int:
        """Persist quotes; return the number of newly stored rows."""
        ...

    def get_quotes(
        self,
        instrument: InstrumentId,
        *,
        start: datetime,
        end: datetime,
        source_id: str | None = None,
        dataset_version: str | None = None,
    ) -> tuple[Quote, ...]:
        """Return stored quotes for one instrument in [start, end]."""
        ...
