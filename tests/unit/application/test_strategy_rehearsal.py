"""Real-path coverage for deployment-bound deterministic strategy rehearsal.

Exercises the M4.1 vertical end to end through the actual canonical
seams — registry resolution, runtime evaluation, deployment-context
binding, risk/policy preparation, and the paper order executor — without
any broker-submit path.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.application.backtest import BacktestResult, DeterministicBacktestService
from quantx.application.strategy_rehearsal import (
    RehearsalInput,
    StrategyRehearsalResult,
    StrategyRehearsalSession,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.enums import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.strategy import (
    SignalAction,
    StrategyDefinition,
    StrategyId,
    StrategyResult,
    StrategySignal,
    TimerRequest,
)
from quantx.domain.value_objects import Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.latency import LatencyModel
from quantx.execution.paper.profile import (
    ExecutionProfile,
    OrderBookLevel,
    OrderBookSnapshot,
    SlippageModel,
)
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.execution import bind_deployment_context
from quantx.strategy.ir import StrategyIR
from quantx.strategy.reference import BuyAndHoldStrategy
from quantx.strategy.registry import StrategyRegistry


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _deployment(
    *, mode: ExecutionMode = ExecutionMode.PAPER, enabled: bool = True
) -> StrategyDeployment:
    return StrategyDeployment(
        deployment_id=StrategyDeploymentId("deploy-1"),
        strategy_id="buy-and-hold",
        strategy_version="1",
        portfolio_id=PortfolioId("portfolio-1"),
        account_id=AccountId("acct-1"),
        market=_market(),
        execution_mode=mode,
        enabled=enabled,
    )


def _ir() -> StrategyIR:
    return StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"),
            "1",
            "Buy and Hold",
            parameters={"quantity": "2"},
        )
    )


def _registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", BuyAndHoldStrategy)
    return registry


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _event(timestamp: datetime | None = None) -> MarketDataEvent:
    instrument = InstrumentId("NSE", "TCS")
    observed_at = timestamp or datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        observed_at,
        instrument,
        Quote(instrument, observed_at, bid=Decimal("99"), ask=Decimal("100")),
    )


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5"))


class _CountingAccounting(FillAccounting):
    """Accounting spy proving fills reach the ledger exactly once."""

    def __init__(self) -> None:
        super().__init__()
        self.applications: list[Fill] = []

    def apply(self, fill: Fill, *, fee: Decimal = Decimal("0")) -> PositionLedgerEntry:
        self.applications.append(fill)
        return super().apply(fill, fee=fee)


def _executor(accounting: _CountingAccounting) -> PaperOrderExecutor:
    profile = ExecutionProfile(
        profile_id="rehearsal",
        version="1",
        slippage_model=SlippageModel.NONE,
        fee_rate=Decimal("0"),
    )
    return PaperOrderExecutor(PaperBroker(profile), accounting)


def _session(
    accounting: _CountingAccounting | None = None,
    *,
    deployment: StrategyDeployment | None = None,
    registry: StrategyRegistry | None = None,
    strategy_ir: StrategyIR | None = None,
) -> tuple[StrategyRehearsalSession, _CountingAccounting]:
    held = accounting or _CountingAccounting()
    session = StrategyRehearsalSession(
        registry=registry or _registry(),
        strategy_ir=strategy_ir or _ir(),
        deployment=deployment or _deployment(),
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        paper_executor=_executor(held),
        financial_state=_financial_state(),
    )
    return session, held


def _inputs(*timestamps: datetime) -> tuple[RehearsalInput, ...]:
    return tuple(
        RehearsalInput(event=_event(observed_at), snapshot=_snapshot())
        for observed_at in timestamps
    )


# ---------------------------------------------------------------------------
# Deployment-context binding
# ---------------------------------------------------------------------------


def test_bind_attaches_deployment_context_to_bare_intent() -> None:
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        strategy_id="buy-and-hold",
        strategy_version="1",
    )
    assert intent.execution_context is None
    bound = bind_deployment_context(intent, _deployment())
    assert bound.execution_context is not None
    assert bound.execution_context.account_id == AccountId("acct-1")
    assert bound.execution_context.portfolio_id == PortfolioId("portfolio-1")
    assert bound.execution_context.deployment_id == StrategyDeploymentId("deploy-1")
    assert bound.execution_context.market == _market()
    assert bound.execution_context.broker_connection_id is None
    assert bound.execution_context.execution_mode is ExecutionMode.PAPER
    assert bound.quantity == Decimal("2")


def test_bind_accepts_matching_context_unchanged() -> None:
    deployment = _deployment()
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        strategy_id="buy-and-hold",
        strategy_version="1",
    )
    bound = bind_deployment_context(intent, deployment)
    assert bind_deployment_context(bound, deployment) == bound


def test_bind_rejects_conflicting_context() -> None:
    deployment = _deployment()
    foreign = ExecutionContext(
        account_id=AccountId("acct-2"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        strategy_id="buy-and-hold",
        strategy_version="1",
        execution_context=foreign,
    )
    with pytest.raises(ValueError, match="does not match deployment"):
        bind_deployment_context(intent, deployment)


# ---------------------------------------------------------------------------
# Session construction guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        ExecutionMode.LIVE,
        ExecutionMode.BACKTEST,
        ExecutionMode.REPLAY,
        ExecutionMode.SHADOW,
    ],
)
def test_session_rejects_non_paper_deployment(mode: ExecutionMode) -> None:
    accounting = _CountingAccounting()
    with pytest.raises(ValueError, match="PAPER deployments only"):
        StrategyRehearsalSession(
            registry=_registry(),
            strategy_ir=_ir(),
            deployment=_deployment(mode=mode),
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
            paper_executor=_executor(accounting),
            financial_state=_financial_state(),
        )


def test_session_rejects_disabled_deployment() -> None:
    accounting = _CountingAccounting()
    with pytest.raises(ValueError, match="disabled"):
        StrategyRehearsalSession(
            registry=_registry(),
            strategy_ir=_ir(),
            deployment=_deployment(enabled=False),
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
            paper_executor=_executor(accounting),
            financial_state=_financial_state(),
        )


def test_session_rejects_unknown_strategy() -> None:
    accounting = _CountingAccounting()
    with pytest.raises(KeyError, match="not registered"):
        StrategyRehearsalSession(
            registry=StrategyRegistry(),
            strategy_ir=_ir(),
            deployment=_deployment(),
            instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
            paper_executor=_executor(accounting),
            financial_state=_financial_state(),
        )


# ---------------------------------------------------------------------------
# Valid rehearsal reaching paper
# ---------------------------------------------------------------------------


def test_valid_rehearsal_reaches_paper_fill_exactly_once() -> None:
    session, accounting = _session()
    result = session.run(
        _inputs(
            datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
            datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
        )
    )

    assert result.deployment == _deployment()
    assert result.strategy_ir == _ir()
    assert len(result.steps) == 2

    first, second = result.steps
    assert first.evaluation.result.signal.action is SignalAction.BUY
    assert first.preparation.request is not None
    assert first.paper_outcome is not None
    assert first.paper_outcome.lifecycle_status is OrderStatus.FILLED
    assert first.paper_outcome.fill is not None
    assert first.paper_outcome.fill.quantity == Decimal("2")
    assert first.note == "paper executed"

    assert second.evaluation.result.signal.action is SignalAction.HOLD
    assert second.evaluation.result.intent is None
    assert second.preparation.request is None
    assert second.paper_outcome is None

    assert len(accounting.applications) == 1
    assert accounting.applications[0] == first.paper_outcome.fill


class _IocEntryStrategy:
    """Test-only IOC entrant: one IOC intent, then HOLD."""

    def __init__(self) -> None:
        self._entered = False

    def on_market_data(self, context: StrategyContext):
        event, ir = context.event, context.ir
        if self._entered:
            return StrategyResult(
                signal=StrategySignal(
                    strategy_id=ir.strategy_id,
                    strategy_version=ir.version,
                    instrument=event.instrument,
                    action=SignalAction.HOLD,
                    confidence=1.0,
                    generated_at=event.timestamp,
                )
            )
        self._entered = True
        return StrategyResult(
            signal=StrategySignal(
                strategy_id=ir.strategy_id,
                strategy_version=ir.version,
                instrument=event.instrument,
                action=SignalAction.BUY,
                confidence=1.0,
                generated_at=event.timestamp,
            ),
            intent=TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("2"),
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.IOC,
                strategy_id=ir.strategy_id.value,
                strategy_version=ir.version,
            ),
        )


def _thin_book() -> OrderBookSnapshot:
    return OrderBookSnapshot(
        bids=(),
        asks=(OrderBookLevel(Decimal("100"), Decimal("1")),),
        observed_at_ns=1_000_000_000,
    )


def test_ioc_partial_fill_cancels_remainder_without_resubmission() -> None:
    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", _IocEntryStrategy)
    session, accounting = _session(registry=registry)
    observed_at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    result = session.run(
        (
            RehearsalInput(
                event=_event(observed_at),
                snapshot=_snapshot(),
                order_book=_thin_book(),
            ),
        )
    )

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.paper_outcome is not None
    assert step.paper_outcome.lifecycle_status is OrderStatus.CANCELLED
    assert step.paper_outcome.fill is not None
    assert step.paper_outcome.fill.quantity == Decimal("1")
    assert len(accounting.applications) == 1
    assert accounting.applications[0].quantity == Decimal("1")


def test_missing_snapshot_produces_no_fill_without_accounting() -> None:
    session, accounting = _session()
    result = session.run((RehearsalInput(event=_event(), snapshot=None),))

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.preparation.request is not None
    assert step.paper_outcome is not None
    assert step.paper_outcome.fill is None
    assert accounting.applications == []


def test_missing_instrument_metadata_is_recorded_as_blocked() -> None:
    accounting = _CountingAccounting()
    session = StrategyRehearsalSession(
        registry=_registry(),
        strategy_ir=_ir(),
        deployment=_deployment(),
        instrument_registry=InMemoryInstrumentRegistry(()),
        paper_executor=_executor(accounting),
        financial_state=_financial_state(),
    )
    result = session.run(_inputs(datetime(2026, 1, 1, 9, 15, tzinfo=UTC)))

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.evaluation is not None
    assert step.preparation is None
    assert step.paper_outcome is None
    assert step.note.startswith("pre-commit preparation failed:")
    assert "instrument metadata unavailable" in step.note
    assert tuple(fault.callback_name for fault in step.faults) == ("strategy_preparation",)
    assert accounting.applications == []


# ---------------------------------------------------------------------------
# Deterministic repeat evaluation and run isolation
# ---------------------------------------------------------------------------


def _order_sequence(result: StrategyRehearsalResult) -> tuple:
    return tuple(
        (
            step.preparation.request.order.instrument,
            step.preparation.request.order.side,
            step.preparation.request.order.quantity,
            step.preparation.request.order.order_type,
        )
        for step in result.steps
        if step.preparation.request is not None
    )


def test_repeat_runs_produce_identical_order_sequences() -> None:
    moments = (
        datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
    )
    first, _ = _session()
    second, _ = _session()
    assert _order_sequence(first.run(_inputs(*moments))) == _order_sequence(
        second.run(_inputs(*moments))
    )


def test_session_is_single_use() -> None:
    session, _ = _session()
    moments = (datetime(2026, 1, 1, 9, 15, tzinfo=UTC),)
    first = session.run(_inputs(*moments))
    assert len(first.steps) == 1
    with pytest.raises(ValueError, match="single-use"):
        session.run(_inputs(*moments))
    # A fresh session still enters on the same first frame: no leaked state.
    fresh, _ = _session()
    assert fresh.run(_inputs(*moments)).steps[0].evaluation.result.signal.action is (
        SignalAction.BUY
    )


# ---------------------------------------------------------------------------
# QX-08 M2 callback/timer semantics
# ---------------------------------------------------------------------------


class _TimerObserver:
    def __init__(self, *, fail_timer: bool = False) -> None:
        self.requested = False
        self.fail_timer = fail_timer
        self.calls: list[tuple[object, ...]] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event = context.event
        assert event is not None
        self.calls.append(("market", event.timestamp))
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


class _CommitThenFailObserver:
    def __init__(self) -> None:
        self.entered = False
        self.calls: list[str] = []
        self.positions_seen: list[tuple[PositionLedgerEntry, ...]] = []
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
                quantity=Decimal("2"),
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

    def on_fill(self, context: StrategyContext, fill: Fill) -> None:
        self.calls.append("on_fill")
        self.positions_seen.append(context.engine.positions.items)
        raise RuntimeError("fill observer failed")

    def on_order_update(self, context: StrategyContext, update) -> None:
        self.calls.append("on_order_update")
        self.order_updates.append(update)


def _registry_for_strategy(strategy) -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", lambda: strategy)
    return registry


def test_timer_dispatch_precedes_entire_equal_timestamp_cohort() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    cohort = start + timedelta(minutes=1)
    later = start + timedelta(minutes=2)
    strategy = _TimerObserver(fail_timer=True)
    session, _ = _session(registry=_registry_for_strategy(strategy))

    result = session.run(_inputs(start, cohort, cohort, later))

    assert strategy.calls == [
        ("market", start),
        ("timer", None, start + timedelta(seconds=30), "timer-1"),
        ("market", later),
    ]
    assert result.steps[0].evaluation is not None
    assert result.steps[1].evaluation is None
    assert result.steps[2].evaluation is None
    assert result.steps[1].note == result.steps[2].note
    assert result.steps[3].evaluation is not None
    assert result.halt is None
    assert tuple(fault.callback_name for fault in result.callback_faults) == ("on_timer",)


def test_due_timer_failure_does_not_skip_other_due_timers() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    cohort = start + timedelta(minutes=1)
    later = start + timedelta(minutes=2)

    class _MultipleDueTimers:
        def __init__(self) -> None:
            self.requested = False
            self.market_times: list[datetime] = []
            self.timer_ids: list[str] = []

        def on_market_data(self, context: StrategyContext) -> StrategyResult:
            event = context.event
            assert event is not None
            self.market_times.append(event.timestamp)
            timers: tuple[TimerRequest, ...] = ()
            if not self.requested:
                self.requested = True
                due_at = event.timestamp + timedelta(seconds=30)
                timers = (
                    TimerRequest("timer-b", event.instrument, due_at),
                    TimerRequest("timer-a", event.instrument, due_at),
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
            self.timer_ids.append(timer.timer_id)
            if timer.timer_id == "timer-a":
                raise RuntimeError("first due timer failed")

    strategy = _MultipleDueTimers()
    session, _ = _session(registry=_registry_for_strategy(strategy))
    result = session.run(_inputs(start, cohort, cohort, later))

    assert strategy.timer_ids == ["timer-a", "timer-b"]
    assert strategy.market_times == [start, later]
    assert result.steps[1].evaluation is None
    assert result.steps[2].evaluation is None
    assert result.steps[3].evaluation is not None
    assert result.halt is None
    assert tuple(fault.callback_name for fault in result.callback_faults) == ("on_timer",)


def test_rehearsal_reports_timers_undelivered_beyond_input_horizon() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    strategy = _TimerObserver()
    session, _ = _session(registry=_registry_for_strategy(strategy))

    result = session.run(_inputs(start))

    assert len(result.undelivered_timers) == 1
    assert result.undelivered_timers[0].timer.timer_id == "timer-1"
    assert "run ended before the timer became due" in result.undelivered_timers[0].reason
    assert strategy.calls == [("market", start)]


def test_precommit_preparation_failure_preserves_timer_and_later_steps() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    later = start + timedelta(minutes=1)
    timer_due = start + timedelta(seconds=30)

    class _TimerAndConflictingIntent:
        entered = False

        def __init__(self) -> None:
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
            foreign = ExecutionContext(
                account_id=AccountId("acct-2"),
                portfolio_id=PortfolioId("portfolio-1"),
                deployment_id=StrategyDeploymentId("deploy-1"),
                market=_market(),
                broker_connection_id=BrokerConnectionId("conn-1"),
                execution_mode=ExecutionMode.PAPER,
            )
            intent = TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("2"),
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
                execution_context=foreign,
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
                timers=(TimerRequest("prep-failure-timer", event.instrument, timer_due),),
            )

        def on_timer(self, context: StrategyContext, timer) -> None:
            self.calls.append(("timer", context.event, context.as_of, timer.timer_id))

    strategy = _TimerAndConflictingIntent()
    session, accounting = _session(registry=_registry_for_strategy(strategy))

    result = session.run(_inputs(start, later))

    first, second = result.steps
    assert first.evaluation is not None
    assert first.preparation is None
    assert first.paper_outcome is None
    assert "pre-commit preparation failed" in first.note
    assert tuple(fault.callback_name for fault in first.faults) == ("strategy_preparation",)
    assert tuple(fault.callback_name for fault in result.callback_faults) == (
        "strategy_preparation",
    )
    assert strategy.calls == [
        ("market", start),
        ("timer", None, timer_due, "prep-failure-timer"),
        ("market", later),
    ]
    assert second.evaluation is not None
    assert second.evaluation.result.signal.action is SignalAction.HOLD
    assert result.halt is None
    assert accounting.applications == []


def test_postcommit_callback_errors_complete_batch_then_latch_halt() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    later = start + timedelta(minutes=1)
    strategy = _CommitThenFailObserver()
    session, accounting = _session(registry=_registry_for_strategy(strategy))

    result = session.run(_inputs(start, later))

    first = result.steps[0]
    assert first.paper_outcome is not None
    assert first.paper_outcome.fill is not None
    assert first.paper_outcome.lifecycle_status is OrderStatus.FILLED
    assert accounting.applications == [first.paper_outcome.fill]
    assert strategy.calls == ["on_fill", "on_order_update"]
    assert len(strategy.positions_seen) == 1
    assert strategy.positions_seen[0][0].quantity == Decimal("2")
    assert len(strategy.order_updates) == 1
    assert strategy.order_updates[0].status is OrderStatus.FILLED
    assert strategy.order_updates[0].remaining_quantity == Decimal("0")
    assert result.halt is not None
    assert result.halt.kind == "POST_COMMIT_CALLBACK_FAILURE"
    assert tuple(fault.callback_name for fault in result.callback_faults) == ("on_fill",)
    assert result.steps[1].evaluation is None
    assert "run halted" in result.steps[1].note


class _HistoryTimerObserver:
    def __init__(self) -> None:
        self.requested = False
        self.timer_contexts: list[StrategyContext] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event = context.event
        assert event is not None
        timers: tuple[TimerRequest, ...] = ()
        if not self.requested:
            self.requested = True
            timers = (
                TimerRequest(
                    "history-timer",
                    event.instrument,
                    event.timestamp + timedelta(minutes=1),
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
        self.timer_contexts.append(context)


def _candle_event(at: datetime, instrument: InstrumentId) -> MarketDataEvent:
    candle = Candle(
        instrument=instrument,
        timeframe="1m",
        timestamp=at,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )
    return MarketDataEvent(MarketDataType.CANDLE, at, instrument, candle)


def test_timer_history_is_prior_only_and_same_instrument() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    other_instrument_time = start + timedelta(seconds=30)
    due_at = start + timedelta(minutes=1)
    tcs = InstrumentId("NSE", "TCS")
    infy = InstrumentId("NSE", "INFY")
    inputs = tuple(
        RehearsalInput(event, _snapshot())
        for event in (
            _candle_event(start, tcs),
            _candle_event(other_instrument_time, infy),
            _candle_event(due_at, tcs),
            _candle_event(due_at + timedelta(minutes=1), tcs),
        )
    )
    strategy = _HistoryTimerObserver()
    strategy_ir = StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"),
            "1",
            "Buy and Hold",
            parameters={"history_bars": "2", "quantity": "2"},
        )
    )
    session, _ = _session(
        registry=_registry_for_strategy(strategy),
        strategy_ir=strategy_ir,
    )

    result = session.run(inputs)

    assert len(strategy.timer_contexts) == 1
    timer_context = strategy.timer_contexts[0]
    assert timer_context.event is None
    assert timer_context.as_of == due_at
    assert tuple(candle.instrument for candle in timer_context.history) == (tcs,)
    assert tuple(candle.timestamp for candle in timer_context.history) == (start,)
    assert result.steps[-1].evaluation is not None


def test_rehearsal_preflight_rejects_nonzero_latency_before_consumption() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    session, _ = _session()
    session._paper_executor.broker.latency = LatencyModel(order_to_market_ms=1)

    with pytest.raises(ValueError, match="nonzero paper execution latency"):
        session.run(_inputs(start))

    session._paper_executor.broker.latency = LatencyModel()
    assert session.run(_inputs(start)).steps[0].evaluation is not None


@pytest.mark.parametrize("history_bars", ["513", "-1"])
def test_rehearsal_rejects_out_of_range_history_bars_with_field_name(
    history_bars: str,
) -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    strategy_ir = StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"),
            "1",
            "Buy and Hold",
            parameters={"history_bars": history_bars, "quantity": "2"},
        )
    )
    session, _ = _session(strategy_ir=strategy_ir)

    with pytest.raises(ValueError, match="history_bars"):
        session.run(_inputs(start))


def test_rehearsal_rejects_regressing_input_timestamps_before_consuming_session() -> None:
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    later = start + timedelta(minutes=1)
    session, _ = _session()

    with pytest.raises(ValueError, match="nondecreasing"):
        session.run(_inputs(later, start))

    assert session.run(_inputs(start)).steps[0].evaluation is not None


# ---------------------------------------------------------------------------
# Malformed and unsupported inputs
# ---------------------------------------------------------------------------


def test_invalid_strategy_result_blocks_step_and_later_event_continues() -> None:
    class _BrokenStrategy:
        def __init__(self) -> None:
            self.calls = 0

        def on_market_data(self, context: StrategyContext):
            self.calls += 1
            if self.calls > 1:
                event = context.event
                assert event is not None
                return StrategyResult(
                    StrategySignal(
                        strategy_id=context.ir.strategy_id,
                        strategy_version=context.ir.version,
                        instrument=event.instrument,
                        action=SignalAction.HOLD,
                        confidence=1.0,
                        generated_at=event.timestamp,
                    )
                )
            return StrategyResult(
                signal=StrategySignal(
                    strategy_id=context.ir.strategy_id,
                    strategy_version=context.ir.version,
                    instrument=context.event.instrument,
                    action=SignalAction.BUY,
                    confidence=1.0,
                    generated_at=context.event.timestamp,
                ),
                intent=TradeIntent(
                    instrument=context.event.instrument,
                    side=OrderSide.SELL,
                    quantity=Decimal("1"),
                    strategy_id=context.ir.strategy_id.value,
                    strategy_version=context.ir.version,
                ),
            )

    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", _BrokenStrategy)
    session, _ = _session(registry=registry)
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    result = session.run(_inputs(start, start + timedelta(minutes=1)))

    assert len(result.steps) == 2
    assert result.steps[0].evaluation is None
    assert result.steps[0].faults
    assert "BUY signal" in result.steps[0].faults[0].message
    assert result.steps[1].evaluation is not None
    assert result.halt is None


def test_venue_mismatch_blocks_precommit_step() -> None:
    session, _ = _session()
    foreign = InstrumentId("BSE", "TCS")
    observed_at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = MarketDataEvent(
        MarketDataType.QUOTE,
        observed_at,
        foreign,
        Quote(foreign, observed_at, bid=Decimal("99"), ask=Decimal("100")),
    )
    result = session.run((RehearsalInput(event=event, snapshot=_snapshot()),))

    assert len(result.steps) == 1
    assert result.steps[0].evaluation is None
    assert "venue" in result.steps[0].faults[0].message


# ---------------------------------------------------------------------------
# Backtest/paper order-sequence parity
# ---------------------------------------------------------------------------


class _BoundEntryStrategy:
    """Test-only entrant emitting deployment-bound intents for parity runs."""

    def __init__(self, context: ExecutionContext) -> None:
        self._context = context
        self._entered = False

    def on_market_data(self, event_context: StrategyContext):
        event, ir = event_context.event, event_context.ir
        if self._entered:
            return StrategyResult(
                signal=StrategySignal(
                    strategy_id=ir.strategy_id,
                    strategy_version=ir.version,
                    instrument=event.instrument,
                    action=SignalAction.HOLD,
                    confidence=1.0,
                    generated_at=event.timestamp,
                )
            )
        self._entered = True
        return StrategyResult(
            signal=StrategySignal(
                strategy_id=ir.strategy_id,
                strategy_version=ir.version,
                instrument=event.instrument,
                action=SignalAction.BUY,
                confidence=1.0,
                generated_at=event.timestamp,
            ),
            intent=TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("2"),
                strategy_id=ir.strategy_id.value,
                strategy_version=ir.version,
                execution_context=self._context,
            ),
        )


def _bound_context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _parity_series() -> HistoricalDataSeries:
    instrument = InstrumentId("NSE", "TCS")
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


def _parity_rehearsal_inputs() -> tuple[RehearsalInput, ...]:
    inputs: list[RehearsalInput] = []
    for observation in _parity_series().observations:
        quote = observation.snapshot
        assert isinstance(quote, Quote)
        event = MarketDataEvent(
            MarketDataType.QUOTE,
            observation.timestamp,
            observation.instrument,
            quote,
        )
        inputs.append(
            RehearsalInput(
                event=event,
                snapshot=MarketSnapshot(
                    bid=quote.bid,
                    ask=quote.ask,
                    last=quote.last if quote.last is not None else quote.ask,
                ),
            )
        )
    return tuple(inputs)


def test_backtest_paper_order_sequence_parity() -> None:
    moments = (
        datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
    )
    bound_strategy = _BoundEntryStrategy(_bound_context())

    def backtest_strategy(frame):
        return bound_strategy.on_market_data(
            StrategyContext(
                MarketDataEvent(
                    MarketDataType.QUOTE,
                    frame.observation.timestamp,
                    frame.observation.instrument,
                    frame.observation.snapshot,
                ),
                _ir(),
            )
        )

    backtest_result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_parity_series(),
        strategy=backtest_strategy,
        financial_state=_financial_state(),
    )
    backtest_sequence = tuple(
        (
            step.strategy_result.intent.instrument,
            step.strategy_result.intent.side,
            step.strategy_result.intent.quantity,
        )
        for step in backtest_result.steps
        if step.strategy_result.intent is not None
    )

    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", lambda: _BoundEntryStrategy(_bound_context()))
    session, _ = _session(registry=registry)
    rehearsal_result = session.run(_inputs(*moments))
    rehearsal_sequence = tuple(
        (
            step.evaluation.result.intent.instrument,
            step.evaluation.result.intent.side,
            step.evaluation.result.intent.quantity,
        )
        for step in rehearsal_result.steps
        if step.evaluation.result.intent is not None
    )

    assert rehearsal_sequence == backtest_sequence
    assert rehearsal_sequence == ((InstrumentId("NSE", "TCS"), OrderSide.BUY, Decimal("2")),)


class _ObservedBuyAndHold(BuyAndHoldStrategy):
    """Capture QX-08 context and observer semantics without changing decisions."""

    def __init__(self) -> None:
        self.contexts: list[StrategyContext] = []
        self.notifications: list[tuple[object, ...]] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        self.contexts.append(context)
        return super().on_market_data(context)

    def on_fill(self, context: StrategyContext, fill: Fill) -> None:
        self.notifications.append(
            (
                "on_fill",
                fill.instrument,
                fill.side,
                fill.quantity,
                fill.price,
                fill.filled_at,
                tuple(
                    (position.instrument, position.quantity)
                    for position in context.engine.positions.items
                ),
                tuple(
                    (
                        order.instrument,
                        order.status,
                        order.filled_quantity,
                        order.remaining_quantity,
                    )
                    for order in context.engine.orders.items
                ),
            )
        )

    def on_order_update(self, context: StrategyContext, update) -> None:
        self.notifications.append(
            (
                "on_order_update",
                update.instrument,
                update.status,
                update.order_quantity,
                update.filled_quantity,
                update.remaining_quantity,
                update.evidence_time,
                update.effective_at,
                tuple(
                    (position.instrument, position.quantity)
                    for position in context.engine.positions.items
                ),
                tuple(
                    (
                        order.instrument,
                        order.status,
                        order.filled_quantity,
                        order.remaining_quantity,
                    )
                    for order in context.engine.orders.items
                ),
            )
        )


def _context_inventory_signature(
    context: StrategyContext,
) -> tuple[tuple[object, ...], ...]:
    return (
        tuple(
            (position.instrument, position.quantity)
            for position in context.engine.positions.items
        ),
        tuple(
            (
                order.instrument,
                order.status,
                order.order_quantity,
                order.filled_quantity,
                order.remaining_quantity,
            )
            for order in context.engine.orders.items
        ),
    )


def _buy_and_hold_driver_run():
    backtest_strategy = _ObservedBuyAndHold()
    backtest_result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_parity_series(),
        strategy=StrategyEvaluationService(backtest_strategy),
        strategy_ir=_ir(),
        financial_state=_financial_state(),
        execution_context=_bound_context(),
    )

    rehearsal_strategy = _ObservedBuyAndHold()
    session, _ = _session(registry=_registry_for_strategy(rehearsal_strategy))
    rehearsal_result = session.run(_parity_rehearsal_inputs())
    return backtest_result, backtest_strategy, rehearsal_result, rehearsal_strategy


def _buy_and_hold_result_signature(
    result: BacktestResult | StrategyRehearsalResult,
    strategy: _ObservedBuyAndHold,
) -> tuple[object, ...]:
    if isinstance(result, StrategyRehearsalResult):
        decisions = tuple(
            (
                step.evaluation.result.signal.action,
                None
                if step.evaluation.result.intent is None
                else (
                    step.evaluation.result.intent.instrument,
                    step.evaluation.result.intent.side,
                    step.evaluation.result.intent.quantity,
                ),
            )
            for step in result.steps
            if step.evaluation is not None
        )
        receipts = tuple(
            (
                step.paper_outcome.lifecycle_status,
                ()
                if step.paper_outcome.fill is None
                else (
                    (
                        step.paper_outcome.fill.instrument,
                        step.paper_outcome.fill.side,
                        step.paper_outcome.fill.quantity,
                        step.paper_outcome.fill.price,
                        step.paper_outcome.fill.filled_at,
                    ),
                ),
            )
            for step in result.steps
            if step.paper_outcome is not None
        )
    else:
        decisions = tuple(
            (
                step.strategy_result.signal.action,
                None
                if step.strategy_result.intent is None
                else (
                    step.strategy_result.intent.instrument,
                    step.strategy_result.intent.side,
                    step.strategy_result.intent.quantity,
                ),
            )
            for step in result.steps
            if step.strategy_result is not None
        )
        receipts = tuple(
            (
                receipt.order_status,
                tuple(
                    (
                        fill.instrument,
                        fill.side,
                        fill.quantity,
                        fill.price,
                        fill.filled_at,
                    )
                    for fill in receipt.fills
                ),
            )
            for receipt in result.receipts
        )

    contexts = tuple(
        (
            context.event.timestamp if context.event is not None else context.as_of,
            *_context_inventory_signature(context),
        )
        for context in strategy.contexts
    )
    faults = tuple(
        (fault.callback_name, fault.exception_type, fault.message)
        for fault in result.callback_faults
    )
    halt = (
        None
        if result.halt is None
        else (result.halt.kind, result.halt.as_of, result.halt.reason)
    )
    return decisions, receipts, contexts, tuple(strategy.notifications), faults, halt


def test_qx08_buy_and_hold_driver_state_and_callback_parity() -> None:
    (
        backtest,
        backtest_strategy,
        rehearsal,
        rehearsal_strategy,
    ) = _buy_and_hold_driver_run()

    backtest_decisions = tuple(
        step.strategy_result.signal.action for step in backtest.steps
    )
    rehearsal_decisions = tuple(
        step.evaluation.result.signal.action for step in rehearsal.steps
    )
    assert backtest_decisions == rehearsal_decisions == (
        SignalAction.BUY,
        SignalAction.HOLD,
    )
    assert len(backtest.receipts) == 1
    assert backtest.receipts[0].order_status is OrderStatus.FILLED
    assert len(backtest.receipts[0].fills) == 1
    assert rehearsal.steps[0].paper_outcome is not None
    assert rehearsal.steps[0].paper_outcome.lifecycle_status is OrderStatus.FILLED
    assert rehearsal.steps[0].paper_outcome.fill is not None

    # The state seen at both market callbacks must agree: known-empty before
    # entry, then the same engine-owned position and no active entry order.
    backtest_contexts = tuple(
        _context_inventory_signature(context) for context in backtest_strategy.contexts
    )
    rehearsal_contexts = tuple(
        _context_inventory_signature(context) for context in rehearsal_strategy.contexts
    )
    assert backtest_contexts == rehearsal_contexts
    assert backtest_contexts[0] == ((), ())
    assert backtest_contexts[1][0] == ((InstrumentId("NSE", "TCS"), Decimal("2")),)
    assert backtest_contexts[1][1] == ()

    assert tuple(item[0] for item in backtest_strategy.notifications) == (
        "on_fill",
        "on_order_update",
    )
    assert tuple(item[0] for item in rehearsal_strategy.notifications) == (
        "on_fill",
        "on_order_update",
    )
    assert backtest_strategy.notifications == rehearsal_strategy.notifications

    # The account dimension is intentionally not conflated: rehearsal has no
    # authoritative valuation tracker, while backtest does. The unavailability
    # and its reason are a contract, not a value to normalize to zero.
    assert (
        rehearsal_strategy.contexts[0].engine.account_availability.value
        == "UNAVAILABLE"
    )
    assert rehearsal_strategy.contexts[0].engine.account_reason
    assert backtest_strategy.contexts[0].engine.account_reason is None


def test_qx08_buy_and_hold_semantics_repeat_across_fresh_runs() -> None:
    first = _buy_and_hold_driver_run()
    second = _buy_and_hold_driver_run()

    first_backtest = _buy_and_hold_result_signature(first[0], first[1])
    second_backtest = _buy_and_hold_result_signature(second[0], second[1])
    first_rehearsal = _buy_and_hold_result_signature(first[2], first[3])
    second_rehearsal = _buy_and_hold_result_signature(second[2], second[3])

    assert first_backtest == second_backtest
    assert first_rehearsal == second_rehearsal
    assert first_backtest == first_rehearsal


class _AcceptedWithoutFillObserver:
    """Place one resting limit, then observe the retained engine order."""

    def __init__(self) -> None:
        self.contexts: list[StrategyContext] = []
        self.notifications: list[tuple[object, ...]] = []

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        self.contexts.append(context)
        event = context.event
        assert event is not None
        if len(self.contexts) > 1:
            return StrategyResult(
                StrategySignal(
                    context.ir.strategy_id,
                    context.ir.version,
                    event.instrument,
                    SignalAction.HOLD,
                    1.0,
                    generated_at=event.timestamp,
                    reason="observe accepted order",
                )
            )
        intent = TradeIntent(
            instrument=event.instrument,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("90"),
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
                reason="rest limit",
            ),
            intent,
        )

    def on_fill(self, context: StrategyContext, fill: Fill) -> None:
        self.notifications.append(
            ("on_fill", fill.quantity, fill.price, fill.filled_at)
        )

    def on_order_update(self, context: StrategyContext, update) -> None:
        self.notifications.append(
            (
                "on_order_update",
                update.status,
                update.order_quantity,
                update.filled_quantity,
                update.remaining_quantity,
                update.evidence_time,
                update.effective_at,
            )
        )


def test_qx08_backtest_rejects_live_execution_context_for_bound_intents() -> None:
    context = replace(_bound_context(), execution_mode=ExecutionMode.LIVE)
    service = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    )

    with pytest.raises(ValueError, match="supported simulated mode"):
        service.run(
            series=_parity_series(),
            strategy=StrategyEvaluationService(BuyAndHoldStrategy()),
            strategy_ir=_ir(),
            financial_state=_financial_state(),
            execution_context=context,
        )


def test_qx08_accepted_without_fill_callback_and_order_inventory_parity() -> None:
    backtest_strategy = _AcceptedWithoutFillObserver()
    backtest_result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=_parity_series(),
        strategy=StrategyEvaluationService(backtest_strategy),
        strategy_ir=_ir(),
        financial_state=_financial_state(),
        execution_context=_bound_context(),
    )

    rehearsal_strategy = _AcceptedWithoutFillObserver()
    session, _ = _session(registry=_registry_for_strategy(rehearsal_strategy))
    rehearsal_result = session.run(_parity_rehearsal_inputs())

    assert len(backtest_result.receipts) == 1
    assert backtest_result.receipts[0].order_status is OrderStatus.ACCEPTED
    assert backtest_result.receipts[0].fills == ()
    assert rehearsal_result.steps[0].paper_outcome is not None
    assert (
        rehearsal_result.steps[0].paper_outcome.lifecycle_status is OrderStatus.ACCEPTED
    )
    assert rehearsal_result.steps[0].paper_outcome.fill is None

    assert tuple(item[0] for item in backtest_strategy.notifications) == (
        "on_order_update",
    )
    assert tuple(item[0] for item in rehearsal_strategy.notifications) == (
        "on_order_update",
    )
    # The backtest paper engine reports ACCEPTED while the rehearsal executor
    # retains SUBMITTED; the normative contract permits either committed
    # nonterminal status, but both must notify and preserve the active order.
    backtest_update = backtest_strategy.notifications[0]
    rehearsal_update = rehearsal_strategy.notifications[0]
    assert backtest_update[1] is OrderStatus.ACCEPTED
    assert rehearsal_update[1] is OrderStatus.SUBMITTED
    assert backtest_update[2:] == rehearsal_update[2:]

    backtest_orders = backtest_strategy.contexts[1].engine.orders.items
    rehearsal_orders = rehearsal_strategy.contexts[1].engine.orders.items
    assert len(backtest_orders) == len(rehearsal_orders) == 1
    assert backtest_orders[0].status is OrderStatus.ACCEPTED
    assert rehearsal_orders[0].status is OrderStatus.SUBMITTED
    assert (
        backtest_orders[0].filled_quantity
        == rehearsal_orders[0].filled_quantity
        == Decimal("0")
    )
    assert (
        backtest_orders[0].remaining_quantity
        == rehearsal_orders[0].remaining_quantity
        == Decimal("1")
    )
    assert backtest_strategy.contexts[1].engine.orders.availability.value == "AVAILABLE"
    assert (
        rehearsal_strategy.contexts[1].engine.orders.availability.value == "AVAILABLE"
    )


# ---------------------------------------------------------------------------
# Deterministic time-source contract
# ---------------------------------------------------------------------------


def test_fill_and_order_use_event_timeline() -> None:
    """A 2026 event must produce 2026 order/fill timestamps, never 1970.

    The rehearsal derives submission time from the market event (zero
    modeled latency here), so the fill lands on the event instant. Order
    creation is pinned to the same instant instead of wall-clock time.
    """
    session, _ = _session()
    event_at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    result = session.run(_inputs(event_at))

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.evaluation.result.signal.generated_at == event_at
    assert step.preparation.request is not None
    assert step.preparation.request.order.created_at == event_at
    assert step.paper_outcome is not None
    assert step.paper_outcome.fill is not None
    assert step.paper_outcome.fill.filled_at == event_at
    assert step.paper_outcome.fill.filled_at.year == 2026


def test_fill_never_precedes_observation_at_zero_latency() -> None:
    session, _ = _session()
    event_at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    result = session.run(_inputs(event_at))

    step = result.steps[0]
    assert step.paper_outcome is not None
    assert step.paper_outcome.fill is not None
    assert step.paper_outcome.fill.filled_at >= event_at
    assert step.preparation.request is not None
    assert step.paper_outcome.fill.filled_at >= step.preparation.request.order.created_at


def test_wall_clock_signal_timestamp_blocks_step_and_later_event_continues() -> None:
    """A strategy omitting generated_at gets wall-clock time, which must not
    silently enter a deterministic rehearsal."""

    class _WallClockSignalStrategy:
        def __init__(self) -> None:
            self.calls = 0

        def on_market_data(self, context: StrategyContext):
            self.calls += 1
            event = context.event
            assert event is not None
            if self.calls == 1:
                signal = StrategySignal(
                    strategy_id=context.ir.strategy_id,
                    strategy_version=context.ir.version,
                    instrument=event.instrument,
                    action=SignalAction.HOLD,
                    confidence=1.0,
                )
            else:
                signal = StrategySignal(
                    strategy_id=context.ir.strategy_id,
                    strategy_version=context.ir.version,
                    instrument=event.instrument,
                    action=SignalAction.HOLD,
                    confidence=1.0,
                    generated_at=event.timestamp,
                )
            return StrategyResult(signal=signal)

    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", _WallClockSignalStrategy)
    session, _ = _session(registry=registry)
    start = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    result = session.run(_inputs(start, start + timedelta(minutes=1)))

    assert len(result.steps) == 2
    assert result.steps[0].evaluation is None
    assert "signal timestamp" in result.steps[0].faults[0].message
    assert result.steps[1].evaluation is not None
    assert result.halt is None


def test_repeat_runs_agree_on_timestamps() -> None:
    """Identical input twice yields identical timestamp-bearing outputs,
    excluding only random identity fields."""
    event_at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    first_session, _ = _session()
    second_session, _ = _session()
    first = first_session.run(_inputs(event_at)).steps[0]
    second = second_session.run(_inputs(event_at)).steps[0]

    assert first.evaluation.result.signal.generated_at == event_at
    assert second.evaluation.result.signal.generated_at == event_at
    assert first.preparation.request is not None
    assert second.preparation.request is not None
    assert first.preparation.request.order.created_at == event_at
    assert second.preparation.request.order.created_at == event_at
    assert first.paper_outcome is not None and first.paper_outcome.fill is not None
    assert second.paper_outcome is not None and second.paper_outcome.fill is not None
    assert first.paper_outcome.fill.filled_at == second.paper_outcome.fill.filled_at == event_at
