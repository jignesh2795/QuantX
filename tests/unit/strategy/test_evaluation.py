from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.replay import HistoricalReplay
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.reference import BuyAndHoldStrategy


def _event() -> MarketDataEvent:
    instrument = InstrumentId("NSE", "TCS")
    timestamp = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("99"), ask=Decimal("100"), last=Decimal("100")),
    )


def _ir():
    return StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"),
            "1",
            "Buy and Hold",
            parameters={"quantity": "2"},
        )
    )


def _series() -> HistoricalDataSeries:
    event = _event()
    snapshot = MarketSnapshot(
        instrument=event.instrument,
        timestamp=event.timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalDataSeries((HistoricalObservation(snapshot, "test", "1", 0),))


def test_replay_adapter_preserves_strategy_semantics() -> None:
    direct = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate(_event(), _ir())
    replay = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(
        HistoricalReplay(_series()).frames()[0], _ir()
    )

    assert replay.event == direct.event
    assert replay.result.signal.strategy_id == direct.result.signal.strategy_id
    assert replay.result.signal.strategy_version == direct.result.signal.strategy_version
    assert replay.result.signal.instrument == direct.result.signal.instrument
    assert replay.result.signal.action is SignalAction.BUY
    assert replay.result.intent is not None
    assert direct.result.intent is not None
    assert replay.result.intent.instrument == direct.result.intent.instrument
    assert replay.result.intent.side == direct.result.intent.side
    assert replay.result.intent.quantity == direct.result.intent.quantity
    assert replay.result.intent.strategy_id == direct.result.intent.strategy_id
    assert replay.result.intent.strategy_version == direct.result.intent.strategy_version


def test_replay_evaluation_is_deterministic_for_identical_input() -> None:
    first = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(
        HistoricalReplay(_series()).frames()[0], _ir()
    )
    second = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(
        HistoricalReplay(_series()).frames()[0], _ir()
    )

    assert first.event == second.event
    assert first.result.signal.strategy_id == second.result.signal.strategy_id
    assert first.result.signal.strategy_version == second.result.signal.strategy_version
    assert first.result.signal.instrument == second.result.signal.instrument
    assert first.result.signal.action is second.result.signal.action
    assert first.result.intent is not None
    assert second.result.intent is not None
    assert first.result.intent.quantity == second.result.intent.quantity
