from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.reference import BuyAndHoldStrategy, BuyThenCloseStrategy


def _event(symbol: str = "TCS") -> MarketDataEvent:
    instrument = InstrumentId("NSE", symbol)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("100"), ask=Decimal("101")),
    )


def _context(strategy_id: str = "buy-and-hold", quantity: str = "2") -> StrategyContext:
    definition = StrategyDefinition(
        StrategyId(strategy_id),
        "1",
        strategy_id,
        parameters={"quantity": quantity},
    )
    return StrategyContext(_event(), StrategyCompiler.compile(definition))


def test_buy_and_hold_emits_one_intent_then_holds() -> None:
    context = _context()
    strategy = BuyAndHoldStrategy()

    first = strategy.on_market_data(context)
    second = strategy.on_market_data(context)

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

    assert strategy.on_market_data(StrategyContext(_event("TCS"), ir)).intent is not None
    assert strategy.on_market_data(StrategyContext(_event("INFY"), ir)).intent is not None


def test_buy_then_close_emits_close_sell_intent() -> None:
    context = _context("buy-then-close")
    strategy = BuyThenCloseStrategy()

    entry = strategy.on_market_data(context)
    close = strategy.on_market_data(context)

    assert entry.signal.action is SignalAction.BUY
    assert entry.intent is not None
    assert close.signal.action is SignalAction.CLOSE
    assert close.intent is not None
    assert close.intent.side.value == "SELL"
    assert close.intent.quantity == Decimal("2")
