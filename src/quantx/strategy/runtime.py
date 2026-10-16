"""Validated invocation boundary for executable strategies."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from quantx.domain.enums import OrderSide
from quantx.domain.market_data import Candle, MarketDataEvent
from quantx.domain.strategy import SignalAction, StrategyResult

from .context import StrategyContext
from .engine_snapshot import EngineStateSnapshot
from .ir import StrategyIR
from .timers import validate_timer_requests


class ExecutableStrategy(Protocol):
    def on_market_data(self, context: StrategyContext) -> StrategyResult: ...


class StrategyRuntime:
    """Invoke a strategy and enforce the mode-agnostic output contract."""

    def __init__(self, strategy: ExecutableStrategy) -> None:
        self._strategy = strategy

    @property
    def callback_target(self) -> ExecutableStrategy:
        """Return this runtime's single run-scoped strategy instance."""
        return self._strategy

    def evaluate(
        self,
        event: MarketDataEvent,
        ir: StrategyIR,
        *,
        engine: EngineStateSnapshot | None = None,
        as_of: datetime | None = None,
        history: tuple[Candle, ...] = (),
    ) -> StrategyResult:
        context = StrategyContext(
            event=event,
            ir=ir,
            as_of=as_of,
            engine=engine,
            history=history,
        )
        result = self._strategy.on_market_data(context)
        self._validate_result(result, context)
        return result

    @staticmethod
    def _validate_result(result: StrategyResult, context: StrategyContext) -> None:
        event = context.event
        if event is None:
            raise ValueError("on_market_data evaluation requires a market event")
        signal = result.signal
        if signal.strategy_id != context.ir.strategy_id:
            raise ValueError("strategy signal id does not match strategy IR")
        if signal.strategy_version != context.ir.version:
            raise ValueError("strategy signal version does not match strategy IR")
        if signal.instrument != event.instrument:
            raise ValueError("strategy signal instrument does not match market event")
        validate_timer_requests(result, event)

        intent = result.intent
        if intent is None:
            return
        if intent.instrument != event.instrument:
            raise ValueError("strategy intent instrument does not match market event")
        if intent.strategy_id != context.ir.strategy_id.value:
            raise ValueError("strategy intent id does not match strategy IR")
        if intent.strategy_version != context.ir.version:
            raise ValueError("strategy intent version does not match strategy IR")
        if signal.action is SignalAction.HOLD:
            raise ValueError("HOLD signal cannot carry an executable intent")
        if signal.action is SignalAction.BUY and intent.side is not OrderSide.BUY:
            raise ValueError("BUY signal must carry a BUY intent")
        if signal.action is SignalAction.SELL and intent.side is not OrderSide.SELL:
            raise ValueError("SELL signal must carry a SELL intent")
