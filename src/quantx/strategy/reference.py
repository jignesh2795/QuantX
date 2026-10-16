"""Reference strategy implementations used by tests and examples."""

from __future__ import annotations

from decimal import Decimal

from quantx.domain.enums import OrderSide
from quantx.domain.market_data import MarketDataEvent
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal

from .context import StrategyContext
from .engine_snapshot import EvidenceAvailability
from .ir import StrategyIR


def _quantity(context: StrategyContext, strategy_name: str) -> Decimal:
    quantity = context.params.get_decimal("quantity", default=Decimal("1"))
    if quantity <= 0:
        raise ValueError(f"{strategy_name} quantity must be positive")
    return quantity


def _legacy_quantity(ir: StrategyIR, strategy_name: str) -> Decimal:
    """Preserve the independent BuyThenClose reference strategy's input behavior."""
    quantity = Decimal(ir.parameter("quantity") or "1")
    if quantity <= 0:
        raise ValueError(f"{strategy_name} quantity must be positive")
    return quantity


def _hold(
    ir: StrategyIR,
    event: MarketDataEvent,
    reason: str,
) -> StrategyResult:
    signal = StrategySignal(
        strategy_id=ir.strategy_id,
        strategy_version=ir.version,
        instrument=event.instrument,
        action=SignalAction.HOLD,
        confidence=1.0,
        generated_at=event.timestamp,
        reason=reason,
    )
    return StrategyResult(signal=signal)


class BuyAndHoldStrategy:
    """Emit BUY only when engine truth shows no position and no active order."""

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event, ir = context.event, context.ir
        if event is None:
            raise ValueError("buy-and-hold requires a market event")
        engine = context.engine
        if (
            engine.positions.availability is not EvidenceAvailability.AVAILABLE
            or engine.orders.availability is not EvidenceAvailability.AVAILABLE
        ):
            return _hold(
                ir,
                event,
                "engine position or order evidence is unavailable; holding",
            )
        if any(
            position.instrument == event.instrument and position.quantity != 0
            for position in engine.positions.items
        ):
            return _hold(ir, event, "engine reports an existing position; holding")
        if any(order.instrument == event.instrument for order in engine.orders.items):
            return _hold(ir, event, "engine reports an active order; holding")

        quantity = _quantity(context, "buy-and-hold")
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
        if event is None:
            raise ValueError("buy-then-close requires a market event")
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

        quantity = _legacy_quantity(ir, "buy-then-close")
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
