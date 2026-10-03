"""Candle-native deterministic backtest convergence coverage.

Candle-backed replay frames must reach the supported backtest boundary
(strategy evaluation, validation, risk) with exact OHLCV intact, while
quote-based paper execution stays explicitly unavailable for candles:
no synthetic bid/ask/last may be invented to force a fill.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from quantx.application.backtest import (
    BacktestDisposition,
    DeterministicBacktestService,
    _reference_price,
)
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Candle, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import (
    SignalAction,
    StrategyDefinition,
    StrategyId,
    StrategyResult,
    StrategySignal,
)
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.replay import HistoricalReplay
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.evaluation import (
    StrategyEvaluationService,
    _event_from_replay_frame,
)
from quantx.strategy.reference import BuyAndHoldStrategy

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

TCS = InstrumentId("NSE", "TCS")

PRECISE = {
    "open": Decimal("100.100000000000000001"),
    "high": Decimal("101.00000000000001"),
    "low": Decimal("99.09799999999999999"),
    "close": Decimal("100.00000000000001"),
    "volume": Decimal("123456789.123456789"),
}


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        TCS,
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash_balance=Money(Decimal("100000"), "INR"),
        available_cash=Money(Decimal("100000"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("100000"), "INR"),
        buying_power=Money(Decimal("100000"), "INR"),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_instrument().market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _candle(timestamp: datetime = T0, **overrides) -> Candle:
    values = {
        "instrument": TCS,
        "timeframe": "1m",
        "timestamp": timestamp,
        "open": Decimal("99"),
        "high": Decimal("101"),
        "low": Decimal("98"),
        "close": Decimal("100"),
        "volume": Decimal("1000"),
    }
    values.update(overrides)
    return Candle(**values)


def _candle_series() -> HistoricalDataSeries:
    return HistoricalDataSeries(
        (
            HistoricalObservation.from_candle(_candle(T0, **PRECISE), "test", "v1", 0),
            HistoricalObservation.from_candle(
                _candle(
                    T1,
                    open=Decimal("100"),
                    close=Decimal("101.5"),
                    high=Decimal("102"),
                    low=Decimal("100"),
                ),
                "test",
                "v1",
                1,
            ),
            HistoricalObservation.from_candle(
                _candle(
                    T2,
                    open=Decimal("101"),
                    close=Decimal("99.5"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                ),
                "test",
                "v1",
                2,
            ),
        )
    )


def _quote_series() -> HistoricalDataSeries:
    first = Quote(
        instrument=TCS,
        timestamp=T0,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    second = Quote(
        instrument=TCS,
        timestamp=T1,
        bid=Decimal("101"),
        ask=Decimal("102"),
        last=Decimal("101"),
    )
    return HistoricalDataSeries(
        (
            HistoricalObservation(first, "test", "1", 0),
            HistoricalObservation(second, "test", "1", 1),
        )
    )


def _ir():
    return StrategyCompiler.compile(
        StrategyDefinition(StrategyId("buy-and-hold"), "1", "Buy and Hold")
    )


def _buy_once_strategy(context: ExecutionContext):
    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("buy-once"),
                "1",
                TCS,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=TCS,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=context,
                strategy_id="buy-once",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)
        signal = StrategySignal(
            StrategyId("buy-once"),
            "1",
            TCS,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    return strategy


# 1. Candle-backed replay reaches the supported evaluation boundary.
def test_candle_frame_evaluation_preserves_exact_payload() -> None:
    frame = HistoricalReplay(_candle_series()).frames()[0]
    evaluated = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(frame, _ir())

    assert evaluated.event.data_type is MarketDataType.CANDLE
    assert evaluated.event.payload is frame.observation.snapshot
    assert evaluated.event.instrument == TCS
    assert evaluated.event.timestamp == T0
    assert evaluated.event.payload.open == PRECISE["open"]
    assert evaluated.event.payload.high == PRECISE["high"]
    assert evaluated.event.payload.low == PRECISE["low"]
    assert evaluated.event.payload.close == PRECISE["close"]
    assert evaluated.event.payload.volume == PRECISE["volume"]
    assert evaluated.result.signal.action is SignalAction.BUY


def test_quote_frame_evaluation_unchanged() -> None:
    frame = HistoricalReplay(_quote_series()).frames()[0]
    evaluated = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(frame, _ir())

    assert evaluated.event.data_type is MarketDataType.QUOTE
    assert evaluated.event.payload == frame.observation.snapshot
    assert evaluated.event.payload.last == Decimal("100")
    assert evaluated.event.payload.bid == Decimal("99")
    assert evaluated.event.payload.ask == Decimal("100")


def test_candle_reference_price_is_close_without_quote_invention() -> None:
    candle = _candle(T0, **PRECISE)

    assert _reference_price(candle) == PRECISE["close"]
    assert str(_reference_price(candle)) == "100.00000000000001"
    assert not hasattr(candle, "bid")
    assert not hasattr(candle, "ask")
    assert not hasattr(candle, "last")


def test_quote_reference_price_unchanged() -> None:
    assert _reference_price(_quote_series().as_tuple()[0].snapshot) == Decimal("100")
    assert _reference_price(_quote_series().as_tuple()[1].snapshot) == Decimal("101")


def test_unsupported_payloads_fail_explicitly() -> None:
    frame = SimpleNamespace(observation=SimpleNamespace(snapshot=object()))
    with pytest.raises(TypeError, match="unsupported replay observation payload"):
        _event_from_replay_frame(frame)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unsupported backtest observation payload"):
        _reference_price(object())  # type: ignore[arg-type]


# 2/4/6. Candle run: strategy, validation, and risk execute; paper
# execution is explicitly blocked instead of inventing a fill.
def test_candle_backtest_run_blocks_execution_explicitly() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=_buy_once_strategy(_context()),
        financial_state=_financial_state(),
    )

    assert len(result.steps) == 3
    blocked = result.steps[0]
    assert blocked.disposition is BacktestDisposition.BLOCKED
    assert "bar-based execution model" in blocked.reason
    assert blocked.risk_result is not None
    assert blocked.policy_result is not None
    assert result.steps[1].disposition is BacktestDisposition.NO_ACTION
    assert result.steps[2].disposition is BacktestDisposition.NO_ACTION
    assert result.executed_count == 0
    assert result.receipts == ()
    for observation in _candle_series():
        assert isinstance(observation.snapshot, Candle)
        assert not isinstance(observation.snapshot, Quote)


def test_candle_run_is_chronological_deterministic_and_reproducible() -> None:
    shuffled = HistoricalDataSeries(tuple(reversed(_candle_series().as_tuple())))

    def run_all():
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
        ).run(
            series=shuffled,
            strategy=_buy_once_strategy(_context()),
            financial_state=_financial_state(),
        )

    first = run_all()
    second = run_all()

    assert [step.timestamp for step in first.steps] == sorted(
        step.timestamp for step in first.steps
    )
    assert [(step.disposition, step.reason) for step in first.steps] == [
        (step.disposition, step.reason) for step in second.steps
    ]
    assert [step.frame_index for step in first.steps] == [0, 1, 2]


def test_candle_run_consumes_no_future_information() -> None:
    seen: list[tuple[datetime, Decimal]] = []
    series = _candle_series()
    expected = tuple((observation.timestamp, observation.snapshot.close) for observation in series)

    def strategy(frame):
        snapshot = frame.observation.snapshot
        assert frame.observation.timestamp == snapshot.timestamp
        seen.append((snapshot.timestamp, snapshot.close))
        signal = StrategySignal(
            StrategyId("observer"),
            "1",
            TCS,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert seen == list(expected)
    assert seen[0][1] == PRECISE["close"]
    assert seen[0][1] != seen[1][1]


def test_candle_evaluation_is_reproducible() -> None:
    frame = HistoricalReplay(_candle_series()).frames()[1]

    first = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(frame, _ir())
    second = StrategyEvaluationService(BuyAndHoldStrategy()).evaluate_replay_frame(frame, _ir())

    assert first.event == second.event
    assert first.result.signal.action is second.result.signal.action


def test_quote_backtest_still_executes() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_quote_series(),
        strategy=_buy_once_strategy(_context()),
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert len(result.receipts) == 1
    assert result.receipts[0].fills[0].price == Decimal("100")
