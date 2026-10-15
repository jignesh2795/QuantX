"""Runtime-neutral strategy evaluation across live and replay inputs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import StrategyResult
from quantx.research.replay import ReplayFrame

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

    def evaluate_replay_frame(
        self,
        frame: ReplayFrame,
        ir: StrategyIR,
        *,
        engine: EngineStateSnapshot | None = None,
        history: tuple[Candle, ...] = (),
    ) -> StrategyEvaluation:
        event = _event_from_replay_frame(frame)
        return self.evaluate(
            event,
            ir,
            engine=engine,
            as_of=frame.observation.timestamp,
            history=history,
        )


def _event_from_replay_frame(frame: ReplayFrame) -> MarketDataEvent:
    snapshot = frame.observation.snapshot
    if isinstance(snapshot, Candle):
        return MarketDataEvent(
            data_type=MarketDataType.CANDLE,
            timestamp=snapshot.timestamp,
            instrument=snapshot.instrument,
            payload=snapshot,
        )
    if isinstance(snapshot, Quote):
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
    raise TypeError(f"unsupported replay observation payload: {type(snapshot).__name__}")
