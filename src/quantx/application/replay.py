"""Application boundary for replay-frame strategy evaluation."""

from __future__ import annotations

from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.research.replay import ReplayFrame
from quantx.strategy.engine_snapshot import EngineStateSnapshot
from quantx.strategy.evaluation import StrategyEvaluation, StrategyEvaluationService
from quantx.strategy.ir import StrategyIR


def event_from_replay_frame(frame: ReplayFrame) -> MarketDataEvent:
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


def evaluate_replay_frame(
    service: StrategyEvaluationService,
    frame: ReplayFrame,
    ir: StrategyIR,
    *,
    engine: EngineStateSnapshot | None = None,
    history: tuple[Candle, ...] = (),
) -> StrategyEvaluation:
    return service.evaluate(
        event_from_replay_frame(frame),
        ir,
        engine=engine,
        as_of=frame.observation.timestamp,
        history=history,
    )


__all__ = ["evaluate_replay_frame", "event_from_replay_frame"]
