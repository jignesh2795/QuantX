"""Market-data adapter port."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

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
