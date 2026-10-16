from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from quantx.application.backtest import (
    AccountStateSamplingPolicy,
    BacktestDisposition,
    BacktestResult,
    DeterministicBacktestService,
)
from quantx.application.strategy_preflight import EventTimeSupport
from quantx.domain.accounts import AccountId
from quantx.domain.clock import Clock, FixedClock, SimulatedClock, SystemClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyContext, PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.strategy import (
    SignalAction,
    StrategyDefinition,
    StrategyId,
    StrategyResult,
    StrategySignal,
    TimerRequest,
)
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
    PercentageBpsChargeModel,
)
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.paper_engine import PaperExecutionEngine, PaperSimulationProfile
from quantx.execution.paper_session import PaperSession
from quantx.persistence import ReceiptRepository
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.provenance import (
    ExecutionConfiguration,
    PolicyConfiguration,
    ResearchProvenance,
    ResearchRunConfiguration,
    SimulationModelIdentity,
    StartingCapitalConfiguration,
    StrategyConfiguration,
)
from quantx.research.replay import HistoricalReplay, MultiSeries
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.ir import StrategyIR


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
            HistoricalObservation(first, "test", "1", 0, dataset_id="nse-eq"),
            HistoricalObservation(second, "test", "1", 1, dataset_id="nse-eq"),
        )
    )


def _tcs_series() -> HistoricalDataSeries:
    instrument = _instrument().instrument_id
    quote = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalDataSeries(
        (HistoricalObservation(quote, "test", "1", 0, dataset_id="nse-eq"),)
    )


def _infy_series() -> HistoricalDataSeries:
    instrument = _second_instrument().instrument_id
    quote = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
        bid=Decimal("199"),
        ask=Decimal("200"),
        last=Decimal("200"),
    )
    return HistoricalDataSeries(
        (HistoricalObservation(quote, "test", "1", 1, dataset_id="nse-eq"),)
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


class _BacktestTimerObserver:
    def __init__(self, *, fail_timer: bool = False) -> None:
        self.requested = False
        self.fail_timer = fail_timer
        self.calls: list[tuple[object, ...]] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event = context.event
        assert event is not None
        self.calls.append(("market", event.timestamp, event.instrument))
        timers: tuple[TimerRequest, ...] = ()
        if not self.requested:
            self.requested = True
            timers = (
                TimerRequest(
                    "timer-1",
                    event.instrument,
                    event.timestamp + timedelta(seconds=30),
                ),
            )
        return StrategyResult(
            signal=StrategySignal(
                context.ir.strategy_id,
                context.ir.version,
                event.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=event.timestamp,
            ),
            timers=timers,
        )

    def on_timer(self, context: StrategyContext, timer) -> None:
        self.calls.append(("timer", context.event, context.as_of, timer.timer_id))
        if self.fail_timer:
            raise RuntimeError("timer observer failed")


class _BacktestCommitThenFailObserver:
    def __init__(self) -> None:
        self.entered = False
        self.calls: list[str] = []
        self.positions_seen: list[tuple[object, ...]] = []
        self.order_updates: list[object] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event = context.event
        assert event is not None
        if self.entered:
            action = SignalAction.HOLD
            intent = None
        else:
            self.entered = True
            action = SignalAction.BUY
            intent = TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=_context(),
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
            )
        return StrategyResult(
            signal=StrategySignal(
                context.ir.strategy_id,
                context.ir.version,
                event.instrument,
                action,
                1.0,
                generated_at=event.timestamp,
            ),
            intent=intent,
        )

    def on_fill(self, context: StrategyContext, fill) -> None:
        self.calls.append("on_fill")
        self.positions_seen.append(context.engine.positions.items)
        raise RuntimeError("fill observer failed")

    def on_order_update(self, context: StrategyContext, update) -> None:
        self.calls.append("on_order_update")
        self.order_updates.append(update)


def _runtime_ir(strategy_id: str) -> StrategyIR:
    return StrategyCompiler.compile(
        StrategyDefinition(StrategyId(strategy_id), "1", strategy_id)
    )


def _timestamped_tcs_series() -> HistoricalDataSeries:
    instrument = _instrument().instrument_id
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    quotes = tuple(
        Quote(
            instrument,
            timestamp,
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        )
        for timestamp in (start, start + timedelta(minutes=1), start + timedelta(minutes=2))
    )
    return HistoricalDataSeries(
        tuple(
            HistoricalObservation(quote, "test", "1", index, dataset_id="nse-eq")
            for index, quote in enumerate(quotes)
        )
    )


def _same_time_infy_series() -> HistoricalDataSeries:
    instrument = _second_instrument().instrument_id
    timestamp = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    quote = Quote(
        instrument,
        timestamp,
        bid=Decimal("199"),
        ask=Decimal("200"),
        last=Decimal("200"),
    )
    return HistoricalDataSeries(
        (HistoricalObservation(quote, "test", "1", 0, dataset_id="nse-eq"),)
    )


def test_timer_dispatch_precedes_entire_equal_timestamp_cohort() -> None:
    strategy = _BacktestTimerObserver(fail_timer=True)
    ir = _runtime_ir("timer-backtest")
    instruments = InMemoryInstrumentRegistry((_instrument(), _second_instrument()))
    result = DeterministicBacktestService(instrument_registry=instruments).run(
        series=(_timestamped_tcs_series(), _same_time_infy_series()),
        strategy=StrategyEvaluationService(strategy),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    later = start + timedelta(minutes=2)
    assert strategy.calls == [
        ("market", start, InstrumentId("NSE", "TCS")),
        ("timer", None, start + timedelta(seconds=30), "timer-1"),
        ("market", later, InstrumentId("NSE", "TCS")),
    ]
    cohort_steps = [
        step
        for step in result.steps
        if step.timestamp == (start + timedelta(minutes=1)).isoformat()
    ]
    assert len(cohort_steps) == 2
    assert all(step.disposition is BacktestDisposition.BLOCKED for step in cohort_steps)
    assert sum(bool(step.faults) for step in cohort_steps) == 1
    assert result.halt is None
    assert tuple(fault.callback_name for fault in result.callback_faults) == ("on_timer",)


def test_active_order_persists_into_next_strategy_context_until_terminal_status() -> None:
    ir = _runtime_ir("active-order-backtest")
    observed_orders: list[tuple[object, ...]] = []

    class _LimitThenObserve:
        def __init__(self) -> None:
            self.submitted = False

        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            event = context.event
            assert event is not None
            observed_orders.append(tuple(context.engine.orders.items))
            if self.submitted:
                return StrategyResult(
                    StrategySignal(
                        context.ir.strategy_id,
                        context.ir.version,
                        event.instrument,
                        SignalAction.HOLD,
                        1.0,
                        generated_at=event.timestamp,
                    )
                )
            self.submitted = True
            intent = TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                order_type=OrderType.LIMIT,
                limit_price=Decimal("90"),
                execution_context=_context(),
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
            )
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    event.instrument,
                    SignalAction.BUY,
                    1.0,
                    generated_at=event.timestamp,
                ),
                intent,
            )

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(_LimitThenObserve()),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    assert len(result.receipts) == 1
    assert result.receipts[0].order_status is OrderStatus.ACCEPTED
    assert result.receipts[0].fills == ()
    assert observed_orders[0] == ()
    assert len(observed_orders[1]) == 1
    assert observed_orders[1][0].status is OrderStatus.ACCEPTED
    assert observed_orders[1][0].remaining_quantity == Decimal("1")


@pytest.mark.parametrize("failure_layer", ("risk", "policy"))
def test_precommit_risk_or_policy_fault_preserves_timer_and_continues(
    failure_layer: str,
) -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    later = start + timedelta(minutes=1)
    final = start + timedelta(minutes=2)
    timer_due = start + timedelta(seconds=30)

    class _FaultTimerStrategy:
        def __init__(self) -> None:
            self.entered = False
            self.calls: list[tuple[object, ...]] = []

        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            event = context.event
            assert event is not None
            self.calls.append(("market", event.timestamp))
            if self.entered:
                return StrategyResult(
                    StrategySignal(
                        context.ir.strategy_id,
                        context.ir.version,
                        event.instrument,
                        SignalAction.HOLD,
                        1.0,
                        generated_at=event.timestamp,
                    )
                )

            self.entered = True
            intent = TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=_context(),
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
            )
            return StrategyResult(
                signal=StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    event.instrument,
                    SignalAction.BUY,
                    1.0,
                    generated_at=event.timestamp,
                ),
                intent=intent,
                timers=(TimerRequest("precommit-timer", event.instrument, timer_due),),
            )

        def on_timer(self, context: StrategyContext, timer) -> None:
            self.calls.append(("timer", context.event, context.as_of, timer.timer_id))

    class _FailingPrecommitEngine:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError(f"{failure_layer} engine failed")

    strategy = _FaultTimerStrategy()
    engine = _FailingPrecommitEngine()
    engine_options = (
        {"risk_engine": engine}
        if failure_layer == "risk"
        else {"policy_engine": engine}
    )
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        **engine_options,
    ).run(
        series=_timestamped_tcs_series(),
        strategy=StrategyEvaluationService(strategy),
        strategy_ir=_runtime_ir(f"precommit-{failure_layer}"),
        financial_state=_financial_state(),
    )

    first = result.steps[0]
    assert first.disposition is BacktestDisposition.BLOCKED
    assert first.receipt is None
    assert "pre-commit" in first.reason
    assert tuple(fault.callback_name for fault in first.faults) == (
        f"{failure_layer}_preparation",
    )
    assert tuple(fault.callback_name for fault in result.callback_faults) == (
        f"{failure_layer}_preparation",
    )
    assert strategy.calls == [
        ("market", start),
        ("timer", None, timer_due, "precommit-timer"),
        ("market", later),
        ("market", final),
    ]
    assert result.halt is None
    assert result.receipts == ()
    assert result.steps[1].disposition is BacktestDisposition.NO_ACTION


def test_clock_drift_between_strategy_and_execution_is_recorded_without_execute() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    ahead = start + timedelta(seconds=1)
    later = start + timedelta(minutes=1)
    engine = _CapturingEngine(clock=FixedClock(start))
    engine.event_time_support = EventTimeSupport.SUPPORTED
    observed: list[datetime] = []
    strategy_ir = _runtime_ir("clock-drift-before-execution")

    class _BuyOnceStrategy:
        def __init__(self) -> None:
            self.entered = False

        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            event = context.event
            assert event is not None
            observed.append(event.timestamp)
            if self.entered:
                action = SignalAction.HOLD
                intent = None
            else:
                self.entered = True
                action = SignalAction.BUY
                intent = TradeIntent(
                    instrument=event.instrument,
                    side=OrderSide.BUY,
                    quantity=Decimal("1"),
                    execution_context=_context(),
                    strategy_id=context.ir.strategy_id.value,
                    strategy_version=context.ir.version,
                )
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    event.instrument,
                    action,
                    1.0,
                    generated_at=event.timestamp,
                ),
                intent,
            )

    class _DriftingRiskEngine:
        def evaluate(self, intent, context) -> RiskResult:
            engine._clock = FixedClock(ahead)
            return RiskResult(RiskDecision.APPROVE, "approved before clock drift")

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        execution_engine=engine,
        risk_engine=_DriftingRiskEngine(),
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(_BuyOnceStrategy()),
        strategy_ir=strategy_ir,
        financial_state=_financial_state(),
    )

    assert observed == [start]
    assert result.steps[0].disposition is BacktestDisposition.BLOCKED
    assert "event-time alignment failed before paper execution" in result.steps[0].reason
    assert result.steps[0].faults[0].callback_name == "event_time_alignment"
    assert result.halt is not None
    assert result.halt.kind == "EVENT_TIME_SUPPORT_VIOLATION"
    assert result.receipts == ()
    assert engine.captured == []
    assert result.steps[1].disposition is BacktestDisposition.BLOCKED


def test_postcommit_callback_errors_complete_batch_then_latch_halt() -> None:
    strategy = _BacktestCommitThenFailObserver()
    ir = _runtime_ir("callback-backtest")
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(strategy),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    assert len(result.receipts) == 1
    assert result.receipts[0].fills
    assert result.ledger[0].quantity == Decimal("1")
    assert strategy.calls == ["on_fill", "on_order_update"]
    assert len(strategy.positions_seen) == 1
    assert strategy.positions_seen[0][0].quantity == Decimal("1")
    assert len(strategy.order_updates) == 1
    assert strategy.order_updates[0].status is OrderStatus.FILLED
    assert strategy.order_updates[0].remaining_quantity == Decimal("0")
    assert result.halt is not None
    assert result.halt.kind == "POST_COMMIT_CALLBACK_FAILURE"
    assert tuple(fault.callback_name for fault in result.callback_faults) == ("on_fill",)
    assert result.steps[1].disposition is BacktestDisposition.BLOCKED
    assert "run halted" in result.steps[1].reason


def test_unexpected_future_effective_receipt_preserves_facts_and_halts() -> None:
    first_frame = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    ahead = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)

    class _JumpClockEngine(_CapturingEngine):
        def execute(self, request, *, snapshot):
            self._clock = FixedClock(ahead)
            return super().execute(request, snapshot=snapshot)

    engine = _JumpClockEngine(clock=FixedClock(first_frame))
    engine.event_time_support = EventTimeSupport.SUPPORTED
    strategy = _BacktestCommitThenFailObserver()
    ir = _runtime_ir("callback-backtest")

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        execution_engine=engine,
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(strategy),
        strategy_ir=ir,
        financial_state=_financial_state(),
    )

    assert len(result.receipts) == 1
    assert result.receipts[0].executed_at == ahead
    assert result.receipts[0].fills
    assert result.steps[0].receipt is result.receipts[0]
    assert result.ledger[0].quantity == Decimal("1")
    assert result.account_states[0].completeness.value == "INCOMPLETE"
    assert result.halt is not None
    assert result.halt.kind == "TEMPORAL_INTEGRITY"
    assert {fault.source for fault in result.temporal_faults} == {"receipt", "fill"}
    assert strategy.calls == []
    assert result.steps[1].disposition is BacktestDisposition.BLOCKED
    assert len(result.account_state_series) == 1


def test_unexpected_early_effective_receipt_preserves_facts_and_halts() -> None:
    first_frame = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    before_frame = first_frame - timedelta(seconds=1)

    class _BackwardsClockEngine(_CapturingEngine):
        def execute(self, request, *, snapshot):
            self._clock = FixedClock(before_frame)
            return super().execute(request, snapshot=snapshot)

    engine = _BackwardsClockEngine(clock=FixedClock(first_frame))
    engine.event_time_support = EventTimeSupport.SUPPORTED
    strategy = _BacktestCommitThenFailObserver()

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        execution_engine=engine,
    ).run(
        series=_series(),
        strategy=StrategyEvaluationService(strategy),
        strategy_ir=_runtime_ir("early-evidence-backtest"),
        financial_state=_financial_state(),
    )

    assert len(result.receipts) == 1
    assert result.receipts[0].executed_at == before_frame
    assert result.receipts[0].fills
    assert result.steps[0].receipt is result.receipts[0]
    assert result.steps[0].disposition is BacktestDisposition.EXECUTED
    assert result.ledger[0].quantity == Decimal("1")
    assert result.account_states[0].timestamp == first_frame
    assert result.account_states[0].completeness.value == "INCOMPLETE"
    assert result.halt is not None
    assert result.halt.kind == "TEMPORAL_INTEGRITY"
    assert {fault.source for fault in result.temporal_faults} == {"receipt", "fill"}
    assert strategy.calls == []
    assert result.steps[1].disposition is BacktestDisposition.BLOCKED
    assert len(result.account_state_series) == 1


def test_qx08_preflight_rejects_clock_ahead_before_first_strategy_callback() -> None:
    ahead = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    engine = _CapturingEngine(clock=FixedClock(ahead))
    engine.event_time_support = EventTimeSupport.SUPPORTED
    ir = _runtime_ir("clock-preflight-backtest")
    observed: list[datetime] = []

    class _SpyStrategy:
        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            assert context.event is not None
            observed.append(context.event.timestamp)
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    context.event.instrument,
                    SignalAction.HOLD,
                    1.0,
                    generated_at=context.event.timestamp,
                )
            )

    with pytest.raises(ValueError, match="start at the first replay frame"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=StrategyEvaluationService(_SpyStrategy()),
            strategy_ir=ir,
            financial_state=_financial_state(),
        )

    assert observed == []
    assert engine.captured == []
    assert engine.events() == ()
    assert engine._receipts == {}


def test_injected_qx08_clock_drift_blocks_before_next_strategy_callback() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    engine = _CapturingEngine(clock=FixedClock(start))
    engine.event_time_support = EventTimeSupport.SUPPORTED
    strategy_ir = _runtime_ir("clock-drift-backtest")
    observed: list[datetime] = []

    class _HoldStrategy:
        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            assert context.event is not None
            observed.append(context.event.timestamp)
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    context.event.instrument,
                    SignalAction.HOLD,
                    1.0,
                    generated_at=context.event.timestamp,
                )
            )

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        execution_engine=engine,
    ).run(
        series=_timestamped_tcs_series(),
        strategy=StrategyEvaluationService(_HoldStrategy()),
        strategy_ir=strategy_ir,
        financial_state=_financial_state(),
    )

    assert observed == [start]
    assert result.halt is not None
    assert result.halt.kind == "EVENT_TIME_SUPPORT_VIOLATION"
    assert result.temporal_faults == ()
    assert result.callback_faults[0].callback_name == "event_time_alignment"
    assert result.steps[1].disposition is BacktestDisposition.BLOCKED
    assert result.steps[2].disposition is BacktestDisposition.BLOCKED
    assert engine.captured == []


def test_callback_driver_rejects_nonzero_execution_latency_before_first_step() -> None:
    ir = _runtime_ir("latency-preflight-backtest")
    called: list[datetime] = []

    class _SpyStrategy:
        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            assert context.event is not None
            called.append(context.event.timestamp)
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    context.event.instrument,
                    SignalAction.HOLD,
                    1.0,
                    generated_at=context.event.timestamp,
                )
            )

    with pytest.raises(ValueError, match="nonzero paper execution latency"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
        ).run(
            series=_series(),
            strategy=StrategyEvaluationService(_SpyStrategy()),
            strategy_ir=ir,
            financial_state=_financial_state(),
            execution_profile=PaperSimulationProfile(latency_ms=1),
        )

    assert called == []


def test_unknown_executor_time_capability_fails_closed() -> None:
    instrument = _instrument()
    engine = _CapturingEngine(clock=SimulatedClock(datetime(2026, 1, 1, 9, 15, tzinfo=UTC)))
    ir = _runtime_ir("preflight-backtest")

    with pytest.raises(ValueError, match="UNKNOWN"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=StrategyEvaluationService(_ParityStrategy()),
            strategy_ir=ir,
            financial_state=_financial_state(),
        )

    assert engine.captured == []
    assert engine.events() == ()
    assert engine._receipts == {}


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
    assert result.account_state_sampling_policy is AccountStateSamplingPolicy.EXACT_CURRENT

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
    series: MultiSeries = (
        _tcs_series(),
        _infy_series(),
    )
    registry = InMemoryInstrumentRegistry((tcs, infy))

    def strategy(frame):
        # Merged replay: frame 0 is TCS at t0, frame 1 is INFY at t1.
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
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    exact = DeterministicBacktestService(instrument_registry=registry).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
        account_state_sampling_policy=AccountStateSamplingPolicy.EXACT_CURRENT,
    )
    assert exact.account_state_sampling_policy is AccountStateSamplingPolicy.EXACT_CURRENT
    # The frame-0 sample precedes that frame's execution: no position yet.
    assert exact.account_state_series[0].cash == Money(Decimal("1000"), "INR")
    assert exact.account_state_series[0].valuation_evidence == ()
    # At frame 1 the TCS position is open but only INFY has a current mark.
    assert exact.account_state_series[1].completeness.value == "INCOMPLETE"

    as_of = DeterministicBacktestService(instrument_registry=registry).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
        account_state_sampling_policy=AccountStateSamplingPolicy.AS_OF_OBSERVED,
    )
    assert as_of.account_state_sampling_policy is AccountStateSamplingPolicy.AS_OF_OBSERVED
    assert as_of.account_state_series[0].cash == Money(Decimal("1000"), "INR")
    second = as_of.account_state_series[1]
    assert second.completeness.value == "COMPLETE"
    assert second.market_value == Money(Decimal("100"), "INR")
    evidence = second.valuation_evidence[0]
    assert evidence.instrument_id == str(tcs.instrument_id)
    assert evidence.mark_price == Decimal("100")
    assert evidence.observed_at == t0
    assert evidence.selected_at == t1
    assert evidence.observed_at < evidence.selected_at
    assert evidence.unavailable is False


def test_backtest_as_of_observed_with_unusable_mark_stays_incomplete() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)
    usable = Quote(
        instrument=tcs.instrument_id,
        timestamp=t0,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    # A later TCS observation with no usable price overwrites the TCS mark.
    priceless = Quote(
        instrument=tcs.instrument_id,
        timestamp=t1,
    )
    later = Quote(
        instrument=infy.instrument_id,
        timestamp=t2,
        bid=Decimal("199"),
        ask=Decimal("200"),
        last=Decimal("200"),
    )
    series: MultiSeries = (
        HistoricalDataSeries(
            (
                HistoricalObservation(usable, "test", "1", 0),
                HistoricalObservation(priceless, "test", "1", 1),
            )
        ),
        HistoricalDataSeries((HistoricalObservation(later, "test", "1", 2),)),
    )
    registry = InMemoryInstrumentRegistry((tcs, infy))

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("unusable-mark"),
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
                strategy_id="unusable-mark",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)
        return StrategyResult(
            StrategySignal(
                StrategyId("unusable-mark"),
                "1",
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    result = DeterministicBacktestService(instrument_registry=registry).run(
        series=series,
        strategy=strategy,
        financial_state=_financial_state(),
        account_state_sampling_policy=AccountStateSamplingPolicy.AS_OF_OBSERVED,
    )
    assert result.executed_count == 1
    assert result.account_state_series[0].cash == Money(Decimal("1000"), "INR")
    # The open TCS position has no usable mark at or before later samples:
    # AS_OF_OBSERVED must not invent one.
    later_samples = [sample for sample in result.account_state_series if sample.timestamp >= t1]
    assert len(later_samples) == 2
    assert all(sample.completeness.value == "INCOMPLETE" for sample in later_samples)
    assert later_samples[0].valuation_evidence[0].unavailable is True


def _provenance() -> ResearchProvenance:
    return ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="1",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="paper-core-v0.3",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg9",
    )


def _hold_all(strategy_id: str):
    def strategy(frame):
        return StrategyResult(
            StrategySignal(
                StrategyId(strategy_id),
                "1",
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    return strategy


def test_backtest_result_provenance_defaults_to_none() -> None:
    instrument = _instrument()
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=_hold_all("no-provenance"),
        financial_state=_financial_state(),
    )

    assert result.provenance is None
    assert not hasattr(result, "dataset_id")
    assert not hasattr(result, "code_revision")


def test_backtest_attaches_caller_provenance_unchanged() -> None:
    instrument = _instrument()
    supplied = _provenance()
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=_hold_all("attached"),
        financial_state=_financial_state(),
        provenance=supplied,
    )

    assert result.provenance is supplied


def test_backtest_identical_provenance_gives_identical_fingerprint() -> None:
    instrument = _instrument()

    def run_with(provenance: ResearchProvenance):
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=_hold_all("fingerprint-stable"),
            financial_state=_financial_state(),
            provenance=provenance,
        )

    first = run_with(_provenance())
    second = run_with(_provenance())

    assert first.provenance is not None
    assert second.provenance is not None
    assert first.provenance.fingerprint() == second.provenance.fingerprint()


def test_backtest_changed_provenance_declaration_changes_fingerprint() -> None:
    instrument = _instrument()
    revised = ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="1",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="paper-core-v0.3",
        simulation_profile="REALISTIC",
        code_revision="def456",
        configuration_revision="cfg9",
    )

    def run_with(provenance: ResearchProvenance):
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=_hold_all("fingerprint-change"),
            financial_state=_financial_state(),
            provenance=provenance,
        )

    first = run_with(_provenance())
    second = run_with(revised)

    assert first.provenance is not None
    assert second.provenance is not None
    assert first.provenance.fingerprint() != second.provenance.fingerprint()


def test_backtest_heterogeneous_datasets_fail_closed() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    first = HistoricalDataSeries(
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
                dataset_id="nse-eq",
            ),
        )
    )
    second = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=infy.instrument_id,
                    timestamp=t1,
                    bid=Decimal("199"),
                    ask=Decimal("200"),
                    last=Decimal("200"),
                ),
                "other",
                "2",
                1,
                dataset_id="other-ds",
            ),
        )
    )

    with pytest.raises(ValueError, match="exactly one dataset"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((tcs, infy))
        ).run(
            series=(first, second),
            strategy=_hold_all("heterogeneous"),
            financial_state=_financial_state(),
            provenance=_provenance(),
        )


def test_backtest_declared_version_mismatch_fails_closed() -> None:
    instrument = _instrument()
    mismatched = ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="v2",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="paper-core-v0.3",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg9",
    )

    with pytest.raises(ValueError, match="does not match"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=_hold_all("mismatch"),
            financial_state=_financial_state(),
            provenance=mismatched,
        )


def test_backtest_shared_dataset_multi_instrument_binding() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    series: MultiSeries = (
        _tcs_series(),
        _infy_series(),
    )
    registry = InMemoryInstrumentRegistry((tcs, infy))

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("bound-multi"),
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
                strategy_id="bound-multi",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)
        return StrategyResult(
            StrategySignal(
                StrategyId("bound-multi"),
                "1",
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    def run_with(policy):
        return DeterministicBacktestService(instrument_registry=registry).run(
            series=series,
            strategy=strategy,
            financial_state=_financial_state(),
            account_state_sampling_policy=policy,
            provenance=_provenance(),
        )

    exact = run_with(AccountStateSamplingPolicy.EXACT_CURRENT)
    as_of = run_with(AccountStateSamplingPolicy.AS_OF_OBSERVED)

    assert exact.provenance is not None
    assert as_of.provenance is not None
    assert exact.provenance.fingerprint() == as_of.provenance.fingerprint()
    assert exact.account_state_series[1].completeness.value == "INCOMPLETE"
    second = as_of.account_state_series[1]
    assert second.completeness.value == "COMPLETE"
    assert second.market_value == Money(Decimal("100"), "INR")
    assert second.valuation_evidence[0].observed_at == t0
    assert len(exact.account_states) == 1


def test_backtest_wrong_dataset_same_source_version_fails_closed() -> None:
    instrument = _instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    other_dataset = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=instrument.instrument_id,
                    timestamp=t0,
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    last=Decimal("100"),
                ),
                "test",
                "1",
                0,
                dataset_id="other-ds",
            ),
        )
    )

    with pytest.raises(ValueError, match="dataset_id"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=other_dataset,
            strategy=_hold_all("wrong-dataset"),
            financial_state=_financial_state(),
            provenance=_provenance(),
        )


def test_backtest_different_sources_same_dataset_binds() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    first = HistoricalDataSeries(
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
                dataset_id="nse-eq",
            ),
        )
    )
    second = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=infy.instrument_id,
                    timestamp=t1,
                    bid=Decimal("199"),
                    ask=Decimal("200"),
                    last=Decimal("200"),
                ),
                "dhan",
                "1",
                1,
                dataset_id="nse-eq",
            ),
        )
    )
    supplied = _provenance()
    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((tcs, infy))
    ).run(
        series=(first, second),
        strategy=_hold_all("shared-dataset"),
        financial_state=_financial_state(),
        provenance=supplied,
    )

    assert result.provenance is supplied
    assert len(result.account_state_series) == 2


def test_backtest_logical_mismatch_in_later_frame_fails_closed() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    first = HistoricalDataSeries(
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
                dataset_id="nse-eq",
            ),
        )
    )
    second = HistoricalDataSeries(
        (
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
                dataset_id="other-ds",
            ),
        )
    )
    calls: list[int] = []

    def strategy(frame):
        calls.append(frame.index)
        return StrategyResult(
            StrategySignal(
                StrategyId("late-mismatch"),
                "1",
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    with pytest.raises(ValueError, match="exactly one dataset"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((tcs, infy))
        ).run(
            series=(first, second),
            strategy=strategy,
            financial_state=_financial_state(),
            provenance=_provenance(),
        )
    assert calls == []


def test_backtest_same_source_multiple_versions_fail_closed() -> None:
    tcs = _instrument()
    infy = _second_instrument()
    t0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    first = HistoricalDataSeries(
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
                dataset_id="nse-eq",
            ),
        )
    )
    second = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=infy.instrument_id,
                    timestamp=t1,
                    bid=Decimal("199"),
                    ask=Decimal("200"),
                    last=Decimal("200"),
                ),
                "test",
                "2",
                1,
                dataset_id="nse-eq",
            ),
        )
    )

    with pytest.raises(ValueError, match="exactly one dataset"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((tcs, infy))
        ).run(
            series=(first, second),
            strategy=_hold_all("multi-version"),
            financial_state=_financial_state(),
            provenance=_provenance(),
        )


def test_backtest_dataset_identity_has_no_normalization() -> None:
    instrument = _instrument()

    for declared in ("NSE-EQ", "nse-eq "):
        variants = ResearchProvenance(
            dataset_id=declared,
            dataset_version="1",
            instrument_master_version="instr-v3",
            market_rule_version="rules-v2",
            execution_model_version="paper-core-v0.3",
            simulation_profile="REALISTIC",
            code_revision="abc123",
            configuration_revision="cfg9",
        )
        with pytest.raises(ValueError, match="dataset_id"):
            DeterministicBacktestService(
                instrument_registry=InMemoryInstrumentRegistry((instrument,))
            ).run(
                series=_series(),
                strategy=_hold_all("no-normalization"),
                financial_state=_financial_state(),
                provenance=variants,
            )


def test_backtest_provenance_object_reused_across_runs() -> None:
    instrument = _instrument()
    supplied = _provenance()

    def run_with():
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=_hold_all("reused"),
            financial_state=_financial_state(),
            provenance=supplied,
        )

    first = run_with()
    second = run_with()

    assert first.provenance is supplied
    assert second.provenance is supplied
    assert first.provenance.fingerprint() == second.provenance.fingerprint()


def _effective_default_configuration() -> ResearchRunConfiguration:
    """Canonical effective configuration of the default paper backtest path."""
    return ResearchRunConfiguration(
        strategy=StrategyConfiguration(
            strategy_id="c12-strategy",
            strategy_version="1",
        ),
        execution=ExecutionConfiguration(
            simulation_profile_name="REALISTIC",
            latency_ms=0,
            slippage_bps=Decimal("0"),
            partial_fill_ratio=Decimal("1"),
            fee_bps=Decimal("0"),
            execution_models=(
                SimulationModelIdentity(model_id="BASIC_BAR", model_version="basic-bar-v4"),
                SimulationModelIdentity(model_id="QUOTE", model_version="paper-core-v0.3"),
            ),
        ),
        allow_incomplete=False,
        account_state_sampling_policy="EXACT_CURRENT",
        policy=PolicyConfiguration(
            granted_capabilities=(),
            live_trading_enabled=False,
            manual_approval=False,
        ),
        starting_capital=StartingCapitalConfiguration(
            capital_source="backtest_configured",
            currency="INR",
            cash_balance=Decimal("1000"),
            available_cash=Decimal("1000"),
            blocked_cash=Decimal("0"),
            margin_used=Decimal("0"),
            margin_available=Decimal("1000"),
            buying_power=Decimal("1000"),
        ),
    )


class _OpaqueChargeModel:
    """A real charge model with no canonical material-parameter representation."""

    def __init__(self) -> None:
        self._model_id = "opaque.charge"
        self._model_version = "9"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_version(self) -> str:
        return self._model_version

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        return ChargeBreakdown(
            currency=context.currency,
            components=(ChargeComponent("opaque", Decimal("1")),),
            model_id=self._model_id,
            model_version=self._model_version,
        )


class _C12CountingStrategy:
    """Authoritative strategy usable through StrategyEvaluationService."""

    def __init__(self) -> None:
        self.calls: list[datetime] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event, ir = context.event, context.ir
        self.calls.append(event.timestamp)
        return StrategyResult(
            StrategySignal(
                ir.strategy_id,
                ir.version,
                event.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=event.timestamp,
            )
        )


def _c12_service(
    instrument_registry: InMemoryInstrumentRegistry,
    execution_engine: PaperExecutionEngine | None = None,
) -> DeterministicBacktestService:
    return DeterministicBacktestService(
        instrument_registry=instrument_registry,
        execution_engine=execution_engine,
    )


def _c12_strategy_ir() -> StrategyIR:
    return StrategyCompiler.compile(
        StrategyDefinition(StrategyId("c12-strategy"), "1", "C12 Strategy")
    )


def _provenance_with(configuration: ResearchRunConfiguration) -> ResearchProvenance:
    return ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="1",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="paper-core-v0.3",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg9",
        run_configuration=configuration,
    )


def test_backtest_accepts_declared_effective_run_configuration() -> None:
    instrument = _instrument()
    supplied = _provenance_with(_effective_default_configuration())
    result = _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
        series=_series(),
        strategy=StrategyEvaluationService(_C12CountingStrategy()),
        strategy_ir=_c12_strategy_ir(),
        financial_state=_financial_state(),
        provenance=supplied,
    )

    assert result.provenance is supplied
    assert result.provenance.run_configuration is not None


def test_backtest_rejects_declared_run_configuration_mismatch() -> None:
    instrument = _instrument()
    wrong = replace(_effective_default_configuration(), allow_incomplete=True)
    counting = _C12CountingStrategy()

    with pytest.raises(ValueError, match="run configuration"):
        _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
            series=_series(),
            strategy=StrategyEvaluationService(counting),
            strategy_ir=_c12_strategy_ir(),
            financial_state=_financial_state(),
            provenance=_provenance_with(wrong),
        )
    assert counting.calls == []


def test_backtest_rejects_strategy_identity_without_authoritative_ir() -> None:
    instrument = _instrument()
    declared = replace(
        _effective_default_configuration(),
        strategy=StrategyConfiguration(strategy_id="sma", strategy_version="1"),
    )

    with pytest.raises(ValueError, match="run configuration"):
        _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
            series=_series(),
            strategy=_hold_all("callable-strategy"),
            financial_state=_financial_state(),
            provenance=_provenance_with(declared),
        )


def test_backtest_run_configuration_tracks_slippage_profile() -> None:
    instrument = _instrument()
    profile = PaperSimulationProfile(slippage_bps=Decimal("5"))
    declared = replace(
        _effective_default_configuration(),
        execution=replace(
            _effective_default_configuration().execution,
            slippage_bps=Decimal("5"),
            slippage_model=SimulationModelIdentity(
                model_id="paper.fixed_bps_slippage",
                model_version="1",
                parameters=(("basis_points", "5"),),
            ),
        ),
    )
    supplied = _provenance_with(declared)
    result = _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
        series=_series(),
        strategy=StrategyEvaluationService(_C12CountingStrategy()),
        strategy_ir=_c12_strategy_ir(),
        financial_state=_financial_state(),
        execution_profile=profile,
        provenance=supplied,
    )
    assert result.provenance is supplied

    # The same provenance must be rejected when the effective slippage differs.
    counting = _C12CountingStrategy()
    with pytest.raises(ValueError, match="run configuration"):
        _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
            series=_series(),
            strategy=StrategyEvaluationService(counting),
            strategy_ir=_c12_strategy_ir(),
            financial_state=_financial_state(),
            execution_profile=profile,
            provenance=_provenance_with(_effective_default_configuration()),
        )
    assert counting.calls == []


def test_backtest_rejects_injected_engine_without_canonical_identity() -> None:
    """Bypass 1: an injected engine has no authoritative model identity."""
    instrument = _instrument()
    counting = _C12CountingStrategy()
    # Declared configuration claims an empty execution-model list, which the
    # rejected implementation silently accepted for injected engines.
    declared = replace(
        _effective_default_configuration(),
        execution=replace(_effective_default_configuration().execution, execution_models=()),
    )
    engine = PaperExecutionEngine(clock=SimulatedClock(datetime(2026, 1, 1, 9, 15, tzinfo=UTC)))

    with pytest.raises(ValueError, match="execution-model identity"):
        _c12_service(InMemoryInstrumentRegistry((instrument,)), execution_engine=engine).run(
            series=_series(),
            strategy=StrategyEvaluationService(counting),
            strategy_ir=_c12_strategy_ir(),
            financial_state=_financial_state(),
            provenance=_provenance_with(declared),
        )
    assert counting.calls == []


def test_backtest_rejects_opaque_charge_model_declared_as_absent() -> None:
    """Bypass 2: a real custom charge model must never record as absent."""
    instrument = _instrument()
    counting = _C12CountingStrategy()
    profile = PaperSimulationProfile(charge_model=_OpaqueChargeModel())

    with pytest.raises(ValueError, match="canonical material-parameter"):
        _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
            series=_series(),
            strategy=StrategyEvaluationService(counting),
            strategy_ir=_c12_strategy_ir(),
            financial_state=_financial_state(),
            execution_profile=profile,
            provenance=_provenance_with(_effective_default_configuration()),
        )
    assert counting.calls == []


def test_backtest_accepts_explicit_percentage_charge_model() -> None:
    """The explicit PercentageBpsChargeModel path stays canonically represented."""
    instrument = _instrument()
    charge = PercentageBpsChargeModel(rate_bps=Decimal("10"))
    profile = PaperSimulationProfile(charge_model=charge)
    declared = replace(
        _effective_default_configuration(),
        execution=replace(
            _effective_default_configuration().execution,
            charge_model=SimulationModelIdentity(
                model_id="paper.percentage_bps",
                model_version="1",
                parameters=(
                    ("component_name", "modeled_fee"),
                    ("rate_bps", "10"),
                ),
            ),
        ),
    )
    supplied = _provenance_with(declared)
    result = _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
        series=_series(),
        strategy=StrategyEvaluationService(_C12CountingStrategy()),
        strategy_ir=_c12_strategy_ir(),
        financial_state=_financial_state(),
        execution_profile=profile,
        provenance=supplied,
    )
    assert result.provenance is supplied


def test_backtest_rejects_bare_callable_with_structured_provenance() -> None:
    """Bypass 3: a bare callable has no canonical strategy identity."""
    instrument = _instrument()
    counting_calls: list[int] = []

    def strategy(frame):
        counting_calls.append(frame.index)
        return StrategyResult(
            StrategySignal(
                StrategyId("bare"),
                "1",
                frame.observation.instrument,
                SignalAction.HOLD,
                1.0,
                generated_at=frame.observation.timestamp,
            )
        )

    # Declared configuration carries no strategy identity at all.
    declared = replace(_effective_default_configuration(), strategy=StrategyConfiguration())
    with pytest.raises(ValueError, match="authoritative strategy identity"):
        _c12_service(InMemoryInstrumentRegistry((instrument,))).run(
            series=_series(),
            strategy=strategy,
            financial_state=_financial_state(),
            provenance=_provenance_with(declared),
        )
    assert counting_calls == []


_PRISTINE_PAPER_ENGINE = PaperExecutionEngine


def _replay_time_recording_engine(monkeypatch) -> list[ApprovedExecutionRequest]:
    """Capture every request the default paper engine sees, post-stamping."""
    import quantx.application.backtest as backtest_module

    captured: list[ApprovedExecutionRequest] = []

    class _RecordingEngine(_PRISTINE_PAPER_ENGINE):
        def execute(self, request, *, snapshot):
            captured.append(request)
            return super().execute(request, snapshot=snapshot)

    monkeypatch.setattr(backtest_module, "PaperExecutionEngine", _RecordingEngine)
    return captured


def _buy_once_strategy(instrument, context):
    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("replay-time"),
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
                strategy_id="replay-time",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)

        signal = StrategySignal(
            StrategyId("replay-time"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    return strategy


def test_backtest_orders_carry_replay_occurrence_time_not_wall_clock(monkeypatch) -> None:
    """Order evidence must carry the replay instant, never the wall-clock default.

    The venue stamps execution time from the same simulation clock; an order
    whose ``created_at`` stayed on the wall clock would claim to be created
    after it executed, corrupting the recorded timeline and any durable
    pending-context evidence that serializes ``created_at``.
    """
    instrument = _instrument()
    context = _context()
    captured = _replay_time_recording_engine(monkeypatch)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=_buy_once_strategy(instrument, context),
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert len(captured) == 1
    order = captured[0].order
    assert order.created_at == datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    receipt = result.receipts[0]
    assert receipt.executed_at == datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    assert order.created_at <= receipt.executed_at


def test_backtest_repeated_runs_produce_identical_order_timestamps(monkeypatch) -> None:
    """Same input data must yield identical order timestamps across runs."""
    instrument = _instrument()
    context = _context()
    first_captured = _replay_time_recording_engine(monkeypatch)

    DeterministicBacktestService(instrument_registry=InMemoryInstrumentRegistry((instrument,))).run(
        series=_series(),
        strategy=_buy_once_strategy(instrument, context),
        financial_state=_financial_state(),
    )

    second_captured = _replay_time_recording_engine(monkeypatch)
    DeterministicBacktestService(instrument_registry=InMemoryInstrumentRegistry((instrument,))).run(
        series=_series(),
        strategy=_buy_once_strategy(instrument, context),
        financial_state=_financial_state(),
    )

    assert len(first_captured) == 1
    assert len(second_captured) == 1
    assert (
        second_captured[0].order.created_at
        == first_captured[0].order.created_at
        == datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    )


def test_backtest_injected_engine_clock_determines_execution_time() -> None:
    """A caller-supplied engine keeps its own execution clock.

    The service stamps the order with the replay occurrence time but must
    not override the caller's time authority: with an aligned injected
    clock the receipt carries the caller's instant, and equivalent runs
    agree on every timestamp.
    """
    frame_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    instrument = _instrument()

    def _run_once() -> BacktestResult:
        caller_clock = SimulatedClock(frame_time)
        engine = PaperExecutionEngine(clock=caller_clock)
        return DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )

    first = _run_once()
    second = _run_once()

    for result in (first, second):
        assert result.executed_count == 1
        receipt = result.receipts[0]
        assert receipt.executed_at == frame_time
        assert receipt.fills, "expected at least one simulated fill"
        for fill in receipt.fills:
            assert fill.filled_at == frame_time
    assert first.receipts[0].executed_at == second.receipts[0].executed_at
    assert [fill.filled_at for fill in first.receipts[0].fills] == [
        fill.filled_at for fill in second.receipts[0].fills
    ]


def test_backtest_rejects_injected_engine_clock_before_replay_time() -> None:
    """An injected clock that contradicts replay time fails closed.

    The service stamps the order with the replay occurrence time; a receipt
    executed before the order was created would corrupt the recorded
    timeline, so the run aborts instead of recording it. The full
    no-side-effects proof lives in
    ``test_backtest_rejected_clock_leaves_no_venue_side_effects``.
    """
    instrument = _instrument()
    caller_clock = SimulatedClock(datetime(2020, 6, 1, 10, 0, tzinfo=UTC))
    engine = PaperExecutionEngine(clock=caller_clock)

    with pytest.raises(ValueError, match="predates the replay frame"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )


def test_backtest_rejects_signal_using_wall_clock_default() -> None:
    """A signal that relies on the wall-clock default must fail closed.

    Omitting ``generated_at`` stamps the process wall clock, which can never
    match the replay frame. The run must reject it instead of letting replay
    evidence silently carry wall-clock time.
    """
    instrument = _instrument()

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("wall-clock-default"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
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


def _evidence_timestamps(
    result: BacktestResult, requests: list[ApprovedExecutionRequest]
) -> tuple[str, ...]:
    """Every timestamp-bearing semantic output of one backtest run, normalized."""
    assert result.executed_count == 1
    assert len(requests) == 1
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt.fills, "expected at least one simulated fill"
    stamps = [
        requests[0].order.created_at.isoformat(),
        *(fill.filled_at.isoformat() for fill in receipt.fills),
        receipt.executed_at.isoformat(),
        *(step.timestamp for step in result.steps),
        *(step.strategy_result.signal.generated_at.isoformat() for step in result.steps),
        *(snapshot.timestamp.isoformat() for snapshot in result.account_states),
        *(snapshot.timestamp.isoformat() for snapshot in result.account_state_series),
    ]
    return tuple(stamps)


def test_backtest_repeated_runs_produce_identical_evidence_timestamps(monkeypatch) -> None:
    """Equivalent replay inputs must not use process wall-clock time.

    Runs the same two-frame series twice and asserts every timestamp-bearing
    semantic output — order creation, fills, receipt execution, steps,
    signals, and account states — is identical across runs and equals the
    replay frame evidence, never the wall clock.
    """
    frame_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC).isoformat()
    second_frame_time = datetime(2026, 1, 1, 9, 16, tzinfo=UTC).isoformat()
    instrument = _instrument()
    context = _context()

    def _run() -> tuple[BacktestResult, list[ApprovedExecutionRequest]]:
        captured = _replay_time_recording_engine(monkeypatch)
        result = DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,))
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, context),
            financial_state=_financial_state(),
        )
        return result, captured

    first_result, first_requests = _run()
    second_result, second_requests = _run()

    first_evidence = _evidence_timestamps(first_result, first_requests)
    second_evidence = _evidence_timestamps(second_result, second_requests)
    assert first_evidence == second_evidence
    assert first_evidence == (
        frame_time,
        frame_time,
        frame_time,
        frame_time,
        second_frame_time,
        frame_time,
        second_frame_time,
        frame_time,
        frame_time,
        second_frame_time,
    )


class _RecordingIdempotencyStore(InMemoryIdempotencyStore):
    """Counts venue idempotency transitions to prove rejected runs are clean."""

    def __init__(self) -> None:
        super().__init__()
        self.reserve_calls: list[tuple[UUID, str]] = []
        self.complete_calls: list[tuple[UUID, str, UUID]] = []

    def reserve_or_get(self, client_order_id, request_fingerprint, pending_context=None):
        self.reserve_calls.append((client_order_id, request_fingerprint))
        return super().reserve_or_get(client_order_id, request_fingerprint, pending_context)

    def complete(self, client_order_id, request_fingerprint, receipt_id):
        self.complete_calls.append((client_order_id, request_fingerprint, receipt_id))
        return super().complete(client_order_id, request_fingerprint, receipt_id)


class _RecordingReceiptRepository(ReceiptRepository):
    """Counts durable receipt writes to prove rejected runs persist nothing."""

    def __init__(self) -> None:
        self._receipts = {}
        self.saves: list = []

    def save(self, receipt) -> None:
        self.saves.append(receipt.receipt_id)
        self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id):
        return self._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id):
        for receipt in self._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None

    def list_by_correlation_id(self, correlation_id):
        return tuple(
            receipt
            for receipt in self._receipts.values()
            if receipt.correlation_id == correlation_id
        )


class _AdvancingClock(Clock):
    """Deterministic clock that advances on every read, like a live feed."""

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._current = start
        self._step = step

    @property
    def is_deterministic(self) -> bool:
        return True

    def now(self) -> datetime:
        current = self._current
        self._current = current + self._step
        return current


class _CapturingEngine(PaperExecutionEngine):
    """Paper engine that records every request it executes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured: list[ApprovedExecutionRequest] = []

    def execute(self, request, *, snapshot):
        self.captured.append(request)
        return super().execute(request, snapshot=snapshot)


def test_backtest_rejected_clock_leaves_no_venue_side_effects() -> None:
    """A rejected injected clock must leave engine and stores untouched.

    The preflight check fires before execution, so a run aborted for a
    clock that predates the replay frame records no idempotency
    reservation or completion, no durable receipt, no in-memory receipt,
    and no lifecycle events.
    """
    instrument = _instrument()
    store = _RecordingIdempotencyStore()
    repository = _RecordingReceiptRepository()
    engine = PaperExecutionEngine(
        clock=SimulatedClock(datetime(2020, 6, 1, 10, 0, tzinfo=UTC)),
        idempotency_store=store,
        receipt_repository=repository,
    )

    with pytest.raises(ValueError, match="predates the replay frame"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )

    assert store.reserve_calls == []
    assert store.complete_calls == []
    assert store.list_pending_contexts() == ()
    assert store.list_pending_recovery_records() == ()
    assert repository.saves == []
    assert engine.events() == ()
    assert engine._receipts == {}


def test_backtest_accepts_injected_clock_ahead_of_replay_time() -> None:
    """A caller clock ahead of replay time is coherent and admitted.

    The order still carries the replay occurrence time while the receipt
    carries the caller's later instant; equivalent runs agree on every
    timestamp.
    """
    frame_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    ahead = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    instrument = _instrument()

    def _run_once() -> tuple[BacktestResult, list[ApprovedExecutionRequest]]:
        engine = _CapturingEngine(clock=FixedClock(ahead))
        result = DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )
        return result, engine.captured

    first_result, first_requests = _run_once()
    second_result, second_requests = _run_once()

    for result, requests in ((first_result, first_requests), (second_result, second_requests)):
        assert result.executed_count == 1
        assert len(requests) == 1
        assert requests[0].order.created_at == frame_time
        receipt = result.receipts[0]
        assert receipt.executed_at == ahead
        assert receipt.fills, "expected at least one simulated fill"
        for fill in receipt.fills:
            assert fill.filled_at == ahead
    assert first_requests[0].order.created_at == second_requests[0].order.created_at
    assert first_result.receipts[0].executed_at == second_result.receipts[0].executed_at


def test_backtest_accepts_advancing_clock_ahead_of_replay_time() -> None:
    """An independently advancing clock stays coherent while ahead.

    Each read moves the clock forward, so venue stamps land after the
    replay occurrence time carried by the order. Equivalent runs with
    fresh clocks agree exactly.
    """
    frame_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    instrument = _instrument()

    def _run_once() -> tuple[BacktestResult, list[ApprovedExecutionRequest]]:
        engine = _CapturingEngine(
            clock=_AdvancingClock(start, timedelta(seconds=1)),
        )
        result = DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )
        return result, engine.captured

    first_result, first_requests = _run_once()
    second_result, second_requests = _run_once()

    for result, requests in ((first_result, first_requests), (second_result, second_requests)):
        assert result.executed_count == 1
        order_time = requests[0].order.created_at
        assert order_time == frame_time
        receipt = result.receipts[0]
        assert receipt.executed_at >= order_time
        assert receipt.fills, "expected at least one simulated fill"
        for fill in receipt.fills:
            assert fill.filled_at >= order_time
    assert first_requests[0].order.created_at == second_requests[0].order.created_at
    assert first_result.receipts[0].executed_at == second_result.receipts[0].executed_at


def test_backtest_rejects_system_clock_for_replay() -> None:
    """Wall-clock time can never back replay evidence, even when ahead.

    A `SystemClock` reads ahead of the historical frames, so the old
    coherence check alone would admit it. The determinism gate rejects it
    before execution, leaving the venue exactly as it was: no idempotency
    reservation or completion, no durable receipt, no retained receipt,
    and no lifecycle events.
    """
    instrument = _instrument()
    store = _RecordingIdempotencyStore()
    repository = _RecordingReceiptRepository()
    engine = PaperExecutionEngine(
        clock=SystemClock(),
        idempotency_store=store,
        receipt_repository=repository,
    )

    with pytest.raises(ValueError, match="must be deterministic for replay"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )

    assert store.reserve_calls == []
    assert store.complete_calls == []
    assert store.list_pending_contexts() == ()
    assert store.list_pending_recovery_records() == ()
    assert repository.saves == []
    assert engine.events() == ()
    assert engine._receipts == {}


class _UndeclaredClock(Clock):
    """Fixed-time clock that does not declare determinism."""

    def __init__(self, current: datetime) -> None:
        self._current = current

    def now(self) -> datetime:
        return self._current


def test_backtest_rejects_clock_without_determinism_declaration() -> None:
    """The conservative default treats undeclared clocks as non-deterministic.

    This clock always returns the replay frame time, yet the run must still
    reject it: replay admits only clocks that explicitly declare the
    deterministic capability, and the rejection must precede execution.
    """
    instrument = _instrument()
    frame_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    engine = PaperExecutionEngine(clock=_UndeclaredClock(frame_time))

    with pytest.raises(ValueError, match="must be deterministic for replay"):
        DeterministicBacktestService(
            instrument_registry=InMemoryInstrumentRegistry((instrument,)),
            execution_engine=engine,
        ).run(
            series=_series(),
            strategy=_buy_once_strategy(instrument, _context()),
            financial_state=_financial_state(),
        )

    assert engine.events() == ()
    assert engine._receipts == {}
