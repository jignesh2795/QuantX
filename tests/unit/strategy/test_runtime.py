from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderSide
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.reference import BuyAndHoldStrategy
from quantx.strategy.runtime import StrategyRuntime


def _event(symbol: str = "TCS") -> MarketDataEvent:
    instrument = InstrumentId("NSE", symbol)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("100"), ask=Decimal("101")),
    )


def _ir(strategy_id: str = "buy-and-hold"):
    return StrategyCompiler.compile(StrategyDefinition(StrategyId(strategy_id), "1", strategy_id))


def test_runtime_accepts_valid_strategy_output() -> None:
    event = _event()
    result = StrategyRuntime(BuyAndHoldStrategy()).evaluate(event, _ir())

    assert result.intent is not None
    assert result.intent.instrument == event.instrument


def test_runtime_rejects_signal_for_wrong_instrument() -> None:
    event = _event("TCS")
    wrong_instrument = InstrumentId("NSE", "INFY")

    class WrongInstrumentStrategy:
        def on_market_data(self, context):
            return StrategyResult(
                signal=StrategySignal(
                    strategy_id=context.ir.strategy_id,
                    strategy_version=context.ir.version,
                    instrument=wrong_instrument,
                    action=SignalAction.BUY,
                    confidence=1.0,
                    generated_at=context.event.timestamp,
                )
            )

    with pytest.raises(ValueError, match="signal instrument"):
        StrategyRuntime(WrongInstrumentStrategy()).evaluate(event, _ir())


def test_runtime_rejects_hold_with_intent() -> None:
    event = _event()

    class InvalidHoldStrategy:
        def on_market_data(self, context):
            return StrategyResult(
                signal=StrategySignal(
                    strategy_id=context.ir.strategy_id,
                    strategy_version=context.ir.version,
                    instrument=context.event.instrument,
                    action=SignalAction.HOLD,
                    confidence=1.0,
                    generated_at=context.event.timestamp,
                ),
                intent=TradeIntent(
                    instrument=context.event.instrument,
                    side=OrderSide.BUY,
                    quantity=Decimal("1"),
                    strategy_id=context.ir.strategy_id.value,
                    strategy_version=context.ir.version,
                ),
            )

    with pytest.raises(ValueError, match="HOLD"):
        StrategyRuntime(InvalidHoldStrategy()).evaluate(event, _ir())
