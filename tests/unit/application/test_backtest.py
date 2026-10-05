from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.backtest import (
    AccountStateSamplingPolicy,
    BacktestDisposition,
    DeterministicBacktestService,
)
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Quote
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyContext, PolicyDecision, PolicyResult
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyResult, StrategySignal, StrategyId
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.replay import HistoricalReplay
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.execution.paper_engine import PaperExecutionEngine
from quantx.execution.paper_session import PaperSession


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _second_instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "INFY"),
        "INFY",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash_balance=Money(Decimal("1000"), "INR"),
        available_cash=Money(Decimal("1000"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("1000"), "INR"),
        buying_power=Money(Decimal("1000"), "INR"),
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


def _series() -> HistoricalDataSeries:
    instrument = _instrument().instrument_id
    first = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    second = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
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


def test_backtest_rejects_intent_strategy_identity_mismatch() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("identity-check"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            execution_context=context,
            strategy_id="different-strategy",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    with pytest.raises(ValueError, match="intent id"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=strategy,
            financial_state=_financial_state(),
        )


def test_backtest_rejects_signal_intent_direction_mismatch() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("direction-check"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            execution_context=context,
            strategy_id="direction-check",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    with pytest.raises(ValueError, match="BUY signal"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=strategy,
            financial_state=_financial_state(),
        )


def test_backtest_rejects_nondeterministic_signal_timestamp() -> None:
    instrument = _instrument()
    context = _context()
    nondeterministic_timestamp = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("timestamp-check"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=nondeterministic_timestamp,
        )
        return StrategyResult(signal)

    with pytest.raises(ValueError, match="timestamp"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=strategy,
            financial_state=_financial_state(),
        )


def test_backtest_composes_replay_strategy_risk_policy_and_paper_execution() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("buy-once"),
                "1",
                instrument.instrument_id,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=instrument.instrument_id,
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
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert result.rejected_count == 0
    assert len(result.receipts) == 1
    assert result.receipts[0].fills[0].price == Decimal("100")
    assert result.receipts[0].executed_at == datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    assert result.ledger[0].quantity == Decimal("1")
    assert result.steps[1].disposition is BacktestDisposition.NO_ACTION


def test_backtest_blocks_risk_rejected_intent_without_execution() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("too-large"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=_frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            required_margin=Decimal("2000"),
            execution_context=context,
            strategy_id="too-large",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 0
    assert all(step.disposition is BacktestDisposition.RISK_REJECTED for step in result.steps)
    assert result.receipts == ()


def test_backtest_requires_approval_when_policy_requires_manual_approval() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("capability-gated"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=_frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            approval_required=True,
            execution_context=context,
            strategy_id="capability-gated",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
        policy_context=PolicyContext(),
    )

    assert result.executed_count == 0
    assert all(step.disposition is BacktestDisposition.APPROVAL_REQUIRED for step in result.steps)


def test_backtest_blocks_intent_when_canonical_market_does_not_match() -> None:
    instrument = _instrument()
    wrong_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    wrong_context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=wrong_market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("bad-market"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            execution_context=wrong_context,
            strategy_id="bad-market",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert all(step.disposition is BacktestDisposition.BLOCKED for step in result.steps)


class _ParityStrategy:
    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event, ir = context.event, context.ir
        signal = StrategySignal(
            ir.strategy_id,
            ir.version,
            event.instrument,
            SignalAction.BUY if event.timestamp.minute == 15 else SignalAction.HOLD,
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


def test_backtest_accepts_runtime_neutral_strategy_evaluation_service() -> None:
    instrument = _instrument()
    ir = StrategyCompiler.compile(
        StrategyDefinition(StrategyId("backtest-parity"), "1", "Backtest Parity")
    )
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(_ParityStrategy()),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert result.rejected_count == 0
    assert result.steps[0].strategy_result.signal.action is SignalAction.BUY
    assert result.steps[1].strategy_result.signal.action is SignalAction.HOLD
    assert result.receipts[0].fills[0].price == Decimal("100")
    assert result.ledger[0].quantity == Decimal("1")


def test_replay_strategy_output_matches_paper_session_execution_input() -> None:
    instrument = _instrument()
    ir = StrategyCompiler.compile(
        StrategyDefinition(StrategyId("replay-paper-parity"), "1", "Replay Paper Parity")
    )
    strategy = _ParityStrategy()
    evaluation = StrategyEvaluationService(strategy)
    frame = HistoricalReplay(_series()).frames()[0]
    evaluated = evaluation.evaluate_replay_frame(frame, ir)
    assert evaluated.result.intent is not None

    from quantx.domain.clock import SimulatedClock

    engine = PaperExecutionEngine(clock=SimulatedClock(frame.observation.timestamp))
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        initial_cash=Money(Decimal("1000"), "INR"),
    )
    request = ApprovedExecutionRequest(
        order=build_order_from_intent(evaluated.result.intent),
        execution_context=evaluated.result.intent.execution_context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )
    paper = session.execute_and_value(request, snapshot=frame.observation.snapshot)

    assert evaluated.event.instrument == frame.observation.instrument
    assert evaluated.event.timestamp == frame.observation.timestamp
    assert paper.execution.fills[0].instrument == evaluated.result.intent.instrument
    assert paper.execution.fills[0].side == evaluated.result.intent.side
    assert paper.execution.fills[0].quantity == evaluated.result.intent.quantity
    assert paper.execution.fills[0].price == Decimal("100")


def test_backtest_exposes_deterministic_account_state_trajectory() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("account-state"),
                "1",
                instrument.instrument_id,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=instrument.instrument_id,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=context,
                strategy_id="account-state",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)

        signal = StrategySignal(
            StrategyId("account-state"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert len(result.account_states) == 1
    state = result.account_states[0]
    assert state.completeness.value == "COMPLETE"
    assert state.timestamp == result.receipts[0].executed_at
    assert state.cash == Money(Decimal("900"), "INR")
    assert state.market_value == Money(Decimal("100"), "INR")
    assert state.equity == Money(Decimal("1000"), "INR")
    assert state.unrealized_pnl == Money.zero("INR")
    assert state.fees == Money.zero("INR")


def test_backtest_exposes_time_indexed_account_state_series() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("series-check"),
                "1",
                instrument.instrument_id,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=instrument.instrument_id,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=context,
                strategy_id="series-check",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)
        signal = StrategySignal(
            StrategyId("series-check"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert len(result.account_states) == 1
    assert len(result.account_state_series) == 2

    first = result.account_state_series[0]
    second = result.account_state_series[1]
    assert first.timestamp == datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    assert second.timestamp == datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    assert first.cash == Money(Decimal("1000"), "INR")
    assert second.cash == Money(Decimal("900"), "INR")
    assert second.market_value == Money(Decimal("101"), "INR")
    assert second.unrealized_pnl == Money(Decimal("1"), "INR")


def test_backtest_multinstrument_sampling_policy_is_explicit() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    series = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=tcs.instrument_id,
                    timestamp=t0,
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    last=Decimal("100"),
                ),
                "test",
                "1",
                0,
            ),
            HistoricalObservation(
                Quote(
                    instrument=infy.instrument_id,
                    timestamp=t1,
                    bid=Decimal("199"),
                    ask=Decimal("200"),
                    last=Decimal("200"),
                ),
                "test",
                "1",
                1,
            ),
        )
    )
    registry = InMemoryInstrumentRegistry((tcs, infy))

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("multi-instrument"),
                "1",
                tcs.instrument_id,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=tcs.instrument_id,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=_context(),
                strategy_id="multi-instrument",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)
        return StrategyResult(
            StrategySignal(
                StrategyId("multi-instrument"),
                "1",
                infy.instrument_id,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    exact = DeterministicBacktestService(
        instrument_registry=registry
    ).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
        account_state_sampling_policy=AccountStateSamplingPolicy.EXACT_CURRENT,
    )
    assert exact.account_state_sampling_policy is AccountStateSamplingPolicy.EXACT_CURRENT
    assert exact.account_state_series[1].completeness.value == "INCOMPLETE"

    as_of = DeterministicBacktestService(
        instrument_registry=registry
    ).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
        account_state_sampling_policy=AccountStateSamplingPolicy.AS_OF_OBSERVED,
    )
    assert as_of.account_state_sampling_policy is AccountStateSamplingPolicy.AS_OF_OBSERVED
    second = as_of.account_state_series[1]
    assert second.completeness.value == "COMPLETE"
    assert second.market_value == Money(Decimal("100"), "INR")
    evidence = second.valuation_evidence[0]
    assert evidence.instrument_id == str(tcs.instrument_id)
    assert evidence.mark_price == Decimal("100")
    assert evidence.observed_at == t0
    assert evidence.selected_at == t1
    assert evidence.unavailable is False
