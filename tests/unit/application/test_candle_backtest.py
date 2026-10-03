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
from quantx.domain.enums import AssetClass, OrderSide, OrderType
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


# Candle MARKET orders fill deterministically at the observed bar close
# through the BASIC_BAR model; no quote fields are invented.
def test_candle_market_order_fills_at_bar_close() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=_buy_once_strategy(_context()),
        financial_state=_financial_state(),
    )

    assert len(result.steps) == 3
    executed = result.steps[0]
    assert executed.disposition is BacktestDisposition.EXECUTED
    assert executed.risk_result is not None
    assert executed.policy_result is not None
    assert result.steps[1].disposition is BacktestDisposition.NO_ACTION
    assert result.steps[2].disposition is BacktestDisposition.NO_ACTION
    assert result.executed_count == 1
    assert len(result.receipts) == 1
    (fill,) = result.receipts[0].fills
    assert fill.price == PRECISE["close"]
    assert str(fill.price) == "100.00000000000001"
    assert fill.quantity == Decimal("1")
    assert "BASIC_BAR" in result.receipts[0].message
    assert any("BASIC_BAR" in item for item in result.receipts[0].assumptions)
    assert result.ledger[0].quantity == Decimal("1")
    for observation in _candle_series():
        assert isinstance(observation.snapshot, Candle)
        assert not isinstance(observation.snapshot, Quote)


def _limit_strategy(context: ExecutionContext):
    def strategy(frame):
        signal = StrategySignal(
            StrategyId("limit-once"),
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
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50"),
            execution_context=context,
            strategy_id="limit-once",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    return strategy


def _stop_strategy(context: ExecutionContext):
    def strategy(frame):
        signal = StrategySignal(
            StrategyId("stop-once"),
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
            order_type=OrderType.STOP,
            stop_price=Decimal("200"),
            execution_context=context,
            strategy_id="stop-once",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    return strategy


def test_candle_limit_order_produces_no_fill_without_invention() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=_limit_strategy(_context()),
        financial_state=_financial_state(),
    )

    assert len(result.steps) == 3
    assert all(step.disposition is BacktestDisposition.EXECUTED for step in result.steps)
    assert len(result.receipts) == 3
    assert all(receipt.fills == () for receipt in result.receipts)
    assert all("no fill was available" in receipt.message for receipt in result.receipts)
    assert result.ledger == ()


def test_candle_crossed_limit_fills_at_bar_close_end_to_end() -> None:
    def strategy(frame):
        signal = StrategySignal(
            StrategyId("limit-e2e"),
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
            order_type=OrderType.LIMIT,
            limit_price=Decimal("101"),
            execution_context=_context(),
            strategy_id="limit-e2e",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 3
    assert len(result.receipts) == 3
    # closes 100.000...01 and 99.5 cross limit=101; close 101.5 does not.
    assert [fill.price for receipt in result.receipts for fill in receipt.fills] == [
        PRECISE["close"],
        Decimal("99.5"),
    ]
    filled = [receipt for receipt in result.receipts if receipt.fills]
    unfilled = [receipt for receipt in result.receipts if not receipt.fills]
    assert len(filled) == 2 and len(unfilled) == 1
    assert all(receipt.model_version == "basic-bar-v2" for receipt in filled)
    assert all("close-cross" in receipt.message for receipt in filled)
    # Unfilled receipts keep the pre-existing generic engine recording.
    assert all(receipt.model_version == "paper-core-v0.3" for receipt in unfilled)
    assert all(receipt.simulated is True for receipt in result.receipts)
    assert result.ledger[0].quantity == Decimal("2")
    assert result.ledger[0].average_price == Decimal("99.750000000000005")
    assert result.data_quality.value == "COMPLETE"


def test_candle_limit_fills_only_crossed_bars() -> None:
    seen: list[tuple[datetime, Decimal]] = []

    def strategy(frame):
        snapshot = frame.observation.snapshot
        seen.append((snapshot.timestamp, snapshot.close))
        signal = StrategySignal(
            StrategyId("limit-selective"),
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
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100.5"),
            execution_context=_context(),
            strategy_id="limit-selective",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    # closes: 100.000...01 (fill), 101.5 (no fill), 99.5 (fill).
    assert [fill.price for receipt in result.receipts for fill in receipt.fills] == [
        PRECISE["close"],
        Decimal("99.5"),
    ]
    assert [step.timestamp for step in result.steps] == [
        T0.isoformat(),
        T1.isoformat(),
        T2.isoformat(),
    ]
    assert seen == [(T0, PRECISE["close"]), (T1, Decimal("101.5")), (T2, Decimal("99.5"))]


def test_candle_stop_order_produces_no_fill_without_invention() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=_stop_strategy(_context()),
        financial_state=_financial_state(),
    )

    assert len(result.steps) == 3
    assert all(receipt.fills == () for receipt in result.receipts)
    assert all("no fill was available" in receipt.message for receipt in result.receipts)
    assert result.ledger == ()


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


def test_candle_receipt_records_basic_bar_identity() -> None:
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=_buy_once_strategy(_context()),
        financial_state=_financial_state(),
    )

    (receipt,) = result.receipts
    assert receipt.model_version == "basic-bar-v2"
    assert "BASIC_BAR" in receipt.message
    assert any("BASIC_BAR" in item for item in receipt.assumptions)
    assert any(item.startswith("slippage_bps=") for item in receipt.assumptions)
    assert receipt.simulated is True
    assert receipt.source == "paper"
    assert receipt.fills[0].price == PRECISE["close"]


def test_mixed_series_records_identity_per_payload() -> None:
    quote = Quote(
        instrument=TCS,
        timestamp=T0,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    series = HistoricalDataSeries(
        (
            HistoricalObservation(quote, "test", "1", 0),
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
        )
    )

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("buy-every-bar"),
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
            execution_context=_context(),
            strategy_id="buy-every-bar",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 2
    quote_receipt, candle_receipt = result.receipts
    assert quote_receipt.model_version == "paper-core-v0.3"
    assert quote_receipt.fills[0].price == Decimal("100")
    assert "BASIC_BAR" not in quote_receipt.message
    assert candle_receipt.model_version == "basic-bar-v2"
    assert candle_receipt.fills[0].price == Decimal("101.5")
    assert "BASIC_BAR" in candle_receipt.message


def test_candle_receipt_identity_is_reproducible() -> None:
    def run_all():
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
        ).run(
            series=_candle_series(),
            strategy=_buy_once_strategy(_context()),
            financial_state=_financial_state(),
        )

    first = run_all()
    second = run_all()

    for left, right in zip(first.receipts, second.receipts, strict=True):
        assert left.model_version == right.model_version == "basic-bar-v2"
        assert left.message == right.message
        assert left.assumptions == right.assumptions
        assert [fill.price for fill in left.fills] == [fill.price for fill in right.fills]
        assert left.simulated is True and right.simulated is True


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


def test_each_candle_fill_uses_its_own_bar_close() -> None:
    closes: list[Decimal] = []

    def strategy(frame):
        snapshot = frame.observation.snapshot
        signal = StrategySignal(
            StrategyId("buy-every-bar"),
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
            execution_context=_context(),
            strategy_id="buy-every-bar",
            strategy_version="1",
        )
        closes.append(snapshot.close)
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 3
    assert [fill.price for receipt in result.receipts for fill in receipt.fills] == closes
    assert closes[0] == PRECISE["close"]
    assert len(set(closes)) == 3


class _CandleParityStrategy:
    """Context-bearing strategy usable through StrategyEvaluationService."""

    def on_market_data(self, context) -> StrategyResult:
        event, ir = context.event, context.ir
        signal = StrategySignal(
            ir.strategy_id,
            ir.version,
            event.instrument,
            SignalAction.BUY if event.timestamp == T0 else SignalAction.HOLD,
            1.0,
            generated_at=event.timestamp,
        )
        if signal.action is SignalAction.HOLD:
            return StrategyResult(signal)
        intent = TradeIntent(
            instrument=event.instrument,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            execution_context=_context(),
            strategy_id=ir.strategy_id.value,
            strategy_version=ir.version,
        )
        return StrategyResult(signal, intent)


def test_candle_end_to_end_replay_to_accounting() -> None:
    ir = StrategyCompiler.compile(StrategyDefinition(StrategyId("candle-e2e"), "1", "Candle E2E"))
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_candle_series(),
        strategy=StrategyEvaluationService(_CandleParityStrategy()),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert result.rejected_count == 0
    assert len(result.receipts) == 1
    assert result.receipts[0].fills[0].price == PRECISE["close"]
    assert result.receipts[0].fills[0].instrument == TCS
    assert result.steps[0].strategy_result.signal.action is SignalAction.BUY
    assert result.steps[1].strategy_result.signal.action is SignalAction.HOLD
    assert result.ledger[0].quantity == Decimal("1")
