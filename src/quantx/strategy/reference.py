"""Reference strategy implementations used by tests and examples."""

from __future__ import annotations

from decimal import Decimal

from quantx.domain.enums import OrderSide
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal

from .context import StrategyContext
from .ir import StrategyIR


def _quantity(ir: StrategyIR, strategy_name: str) -> Decimal:
    quantity = Decimal(ir.parameter("quantity") or "1")
    if quantity <= 0:
        raise ValueError(f"{strategy_name} quantity must be positive")
    return quantity


class BuyAndHoldStrategy:
    """Emit one BUY intent per instrument, then remain in HOLD state."""

    def __init__(self) -> None:
        self._entered: set[str] = set()

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event, ir = context.event, context.ir
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

        quantity = _quantity(ir, "buy-and-hold")
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


class BuyThenCloseStrategy:
    """Enter long once, then emit a close signal and SELL intent on the next event."""

    def __init__(self) -> None:
        self._entered: set[str] = set()
        self._closed: set[str] = set()

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event, ir = context.event, context.ir
        key = str(event.instrument)

        if key in self._closed:
            signal = StrategySignal(
                strategy_id=ir.strategy_id,
                strategy_version=ir.version,
                instrument=event.instrument,
                action=SignalAction.HOLD,
                confidence=1.0,
                generated_at=event.timestamp,
                reason="position already closed",
            )
            return StrategyResult(signal=signal)

        quantity = _quantity(ir, "buy-then-close")
        if key not in self._entered:
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

        self._closed.add(key)
        signal = StrategySignal(
            strategy_id=ir.strategy_id,
            strategy_version=ir.version,
            instrument=event.instrument,
            action=SignalAction.CLOSE,
            confidence=1.0,
            generated_at=event.timestamp,
            reason="close long position",
        )
        intent = TradeIntent(
            instrument=event.instrument,
            side=OrderSide.SELL,
            quantity=quantity,
            strategy_id=ir.strategy_id.value,
            strategy_version=ir.version,
        )
        return StrategyResult(signal=signal, intent=intent)
