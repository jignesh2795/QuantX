from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import StrategyDefinition, StrategyId, SignalAction
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.reference import BuyAndHoldStrategy


def _event(symbol: str = "TCS") -> MarketDataEvent:
    instrument = InstrumentId("NSE", symbol)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("100"), ask=Decimal("101")),
    )


def test_buy_and_hold_emits_one_intent_then_holds() -> None:
    definition = StrategyDefinition(
        StrategyId("buy-and-hold"),
        "1",
        "Buy and Hold",
        parameters={"quantity": "2"},
    )
    ir = StrategyCompiler.compile(definition)
    strategy = BuyAndHoldStrategy()

    first = strategy.on_market_data(_event(), ir)
    second = strategy.on_market_data(_event(), ir)

    assert first.signal.action is SignalAction.BUY
    assert first.intent is not None
    assert first.intent.quantity == Decimal("2")
    assert first.intent.strategy_id == "buy-and-hold"
    assert first.intent.strategy_version == "1"
    assert second.signal.action is SignalAction.HOLD
    assert second.intent is None


def test_buy_and_hold_tracks_instruments_independently() -> None:
    definition = StrategyDefinition(StrategyId("buy-and-hold"), "1", "Buy and Hold")
    ir = StrategyCompiler.compile(definition)
    strategy = BuyAndHoldStrategy()

    assert strategy.on_market_data(_event("TCS"), ir).intent is not None
    assert strategy.on_market_data(_event("INFY"), ir).intent is not None
