"""Reference strategy implementations used by tests and examples."""

from __future__ import annotations

from decimal import Decimal

from quantx.domain.enums import OrderSide
from quantx.domain.market_data import MarketDataEvent
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal

from .ir import StrategyIR


class BuyAndHoldStrategy:
    """Emit one BUY intent per instrument, then remain in HOLD state."""

    def __init__(self) -> None:
        self._entered: set[str] = set()

    def on_market_data(self, event: MarketDataEvent, ir: StrategyIR) -> StrategyResult:
        key = str(event.instrument)
        if key in self._entered:
            signal = StrategySignal(
                strategy_id=ir.strategy_id,
                strategy_version=ir.version,
                instrument=event.instrument,
                action=SignalAction.HOLD,
                confidence=1.0,
                generated_at=event.timestamp,
                reason="position already entered",
            )
            return StrategyResult(signal=signal)

        quantity_text = ir.parameter("quantity") or "1"
        quantity = Decimal(quantity_text)
        if quantity <= 0:
            raise ValueError("buy-and-hold quantity must be positive")
        self._entered.add(key)
        signal = StrategySignal(
            strategy_id=ir.strategy_id,
            strategy_version=ir.version,
            instrument=event.instrument,
            action=SignalAction.BUY,
            confidence=1.0,
            generated_at=event.timestamp,
            reason="initial entry",
        )
        intent = TradeIntent(
            instrument=event.instrument,
            side=OrderSide.BUY,
            quantity=quantity,
            strategy_id=ir.strategy_id.value,
            strategy_version=ir.version,
        )
        return StrategyResult(signal=signal, intent=intent)
