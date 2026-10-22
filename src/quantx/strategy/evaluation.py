"""Runtime-neutral strategy evaluation over normalized market-data events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quantx.domain.market_data import Candle, MarketDataEvent
from quantx.domain.strategy import StrategyResult

from .engine_snapshot import EngineStateSnapshot
from .ir import StrategyIR
from .runtime import ExecutableStrategy, StrategyRuntime


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    """One strategy decision at a deterministic market-data timestamp."""

    event: MarketDataEvent
    result: StrategyResult


class StrategyEvaluationService:
    """Evaluate one strategy with optional immutable, driver-owned context facts."""

    def __init__(self, strategy: ExecutableStrategy) -> None:
        self._runtime = StrategyRuntime(strategy)

    @property
    def callback_target(self) -> ExecutableStrategy:
        """The fresh run-scoped strategy instance for optional observer callbacks."""
        return self._runtime.callback_target

    def evaluate(
        self,
        event: MarketDataEvent,
        ir: StrategyIR,
        *,
        engine: EngineStateSnapshot | None = None,
        as_of: datetime | None = None,
        history: tuple[Candle, ...] = (),
    ) -> StrategyEvaluation:
        return StrategyEvaluation(
            event=event,
            result=self._runtime.evaluate(
                event,
                ir,
                engine=engine,
                as_of=as_of,
                history=history,
            ),
        )
