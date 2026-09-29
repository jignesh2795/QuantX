"""Validated invocation boundary for executable strategies."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.market_data import MarketDataEvent
from quantx.domain.strategy import StrategyResult

from .context import StrategyContext
from .ir import StrategyIR


class ExecutableStrategy(Protocol):
    def on_market_data(self, context: StrategyContext) -> StrategyResult: ...


class StrategyRuntime:
    """Invoke a strategy and enforce the mode-agnostic output contract."""

    def __init__(self, strategy: ExecutableStrategy) -> None:
        self._strategy = strategy

    def evaluate(self, event: MarketDataEvent, ir: StrategyIR) -> StrategyResult:
        context = StrategyContext(event=event, ir=ir)
        result = self._strategy.on_market_data(context)
        self._validate_result(result, context)
        return result

    @staticmethod
    def _validate_result(result: StrategyResult, context: StrategyContext) -> None:
        signal = result.signal
        if signal.strategy_id != context.ir.strategy_id:
            raise ValueError("strategy signal id does not match strategy IR")
        if signal.strategy_version != context.ir.version:
            raise ValueError("strategy signal version does not match strategy IR")
        if signal.instrument != context.event.instrument:
            raise ValueError("strategy signal instrument does not match market event")

        intent = result.intent
        if intent is None:
            return
        if intent.instrument != context.event.instrument:
            raise ValueError("strategy intent instrument does not match market event")
        if intent.strategy_id != context.ir.strategy_id.value:
            raise ValueError("strategy intent id does not match strategy IR")
        if intent.strategy_version != context.ir.version:
            raise ValueError("strategy intent version does not match strategy IR")
        if signal.action.name == "HOLD":
            raise ValueError("HOLD signal cannot carry an executable intent")
