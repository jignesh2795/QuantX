from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId
from quantx.ports.market_data import MarketDataPort


class ReferenceMarketData:
    def __init__(self, quote: Quote, candles: tuple[Candle, ...]) -> None:
        self._quote = quote
        self._candles = candles
        self.subscribed: set[InstrumentId] = set()

    def quote(self, instrument: InstrumentId) -> Quote | None:
        return self._quote if instrument == self._quote.instrument else None

    def candles(self, instrument, *, timeframe, start, end):
        return tuple(
            candle
            for candle in self._candles
            if candle.instrument == instrument
            and candle.timeframe == timeframe
            and start <= candle.timestamp <= end
        )

    def subscribe(self, instruments):
        self.subscribed.update(instruments)

    def unsubscribe(self, instruments):
        self.subscribed.difference_update(instruments)


def test_reference_market_data_adapter_conforms_to_port_behavior() -> None:
    instrument = InstrumentId("NSE", "TCS")
    first = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    quote = Quote(instrument, first, bid=Decimal("99"), ask=Decimal("100"), last=Decimal("100"))
    candle = Candle(
        instrument,
        "1m",
        first,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("1000"),
    )
    adapter: MarketDataPort = ReferenceMarketData(quote, (candle,))

    assert isinstance(adapter, MarketDataPort)
    assert adapter.quote(instrument) == quote
    assert tuple(adapter.candles(instrument, timeframe="1m", start=first, end=first)) == (candle,)

    adapter.subscribe((instrument,))
    assert instrument in adapter.subscribed
    adapter.unsubscribe((instrument,))
    assert instrument not in adapter.subscribed
