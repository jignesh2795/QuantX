"""Runtime-neutral strategy evaluation across live and replay inputs."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.research.replay import ReplayFrame

from .ir import StrategyIR
from .runtime import ExecutableStrategy, StrategyRuntime


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    """One strategy decision at a deterministic market-data timestamp."""

    event: MarketDataEvent
    result: object


class StrategyEvaluationService:
    """Evaluate the same executable strategy from canonical market-data events."""

    def __init__(self, strategy: ExecutableStrategy) -> None:
        self._runtime = StrategyRuntime(strategy)

    def evaluate(self, event: MarketDataEvent, ir: StrategyIR) -> StrategyEvaluation:
        return StrategyEvaluation(
            event=event,
            result=self._runtime.evaluate(event, ir),
        )

    def evaluate_replay_frame(self, frame: ReplayFrame, ir: StrategyIR) -> StrategyEvaluation:
        return self.evaluate(_event_from_replay_frame(frame), ir)


def _event_from_replay_frame(frame: ReplayFrame) -> MarketDataEvent:
    snapshot = frame.observation.snapshot
    payload = Quote(
        instrument=snapshot.instrument,
        timestamp=snapshot.timestamp,
        bid=snapshot.bid,
        ask=snapshot.ask,
        last=snapshot.last,
        bid_size=snapshot.bid_size,
        ask_size=snapshot.ask_size,
    )
    return MarketDataEvent(
        data_type=MarketDataType.QUOTE,
        timestamp=snapshot.timestamp,
        instrument=snapshot.instrument,
        payload=payload,
    )
