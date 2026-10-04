"""R1-A regression tests: deterministic LIVE risk invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import (
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
)
from quantx.domain.value_objects import Money
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.trading_gate import DurableTradingGate
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport

EVALUATED_AT = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 1, 1, 9, 29, tzinfo=UTC)


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


def _financial() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _context(**overrides) -> RiskContext:
    values: dict = {"reference_price": Decimal("100")}
    values.update(overrides)
    return RiskContext(
        _instrument(),
        _financial(),
        broker_constraints=values.pop("broker_constraints", ()),
        reference_price=values.pop("reference_price"),
    )


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )


def _intent(**overrides) -> TradeIntent:
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "required_margin": Decimal("1000"),
        "required_capabilities": frozenset({"ORDER_SUBMISSION"}),
        "execution_context": _execution_context(),
    }
    values.update(overrides)
    return TradeIntent(**values)


def _limits(**overrides) -> RiskLimits:
    values: dict = {
        "max_order_notional": Decimal("100000"),
        "max_position_notional": Decimal("100000"),
        "max_portfolio_exposure": Decimal("1000000"),
        "max_instrument_concentration": Decimal("0.9"),
        "max_daily_loss": Decimal("10000"),
        "max_drawdown": Decimal("0.5"),
        "max_snapshot_age": timedelta(minutes=5),
    }
    values.update(overrides)
    return RiskLimits(**values)


def _snapshot(**overrides) -> RiskSnapshot:
    values: dict = {
        "observed_at": OBSERVED_AT,
        "current_position_exposure": Decimal("0"),
        "current_instrument_exposure": Decimal("0"),
        "current_portfolio_exposure": Decimal("100000"),
        "available_margin": Decimal("100000"),
        "required_margin": Decimal("1000"),
        "daily_pnl": Decimal("0"),
        "equity": Decimal("100000"),
        "high_water_mark": Decimal("100000"),
    }
    values.update(overrides)
    return RiskSnapshot(**values)


def _evaluate(intent=None, context=None, limits=None, snapshot=None) -> RiskResult:
    return PreTradeRiskEngine().evaluate_with_limits(
        intent or _intent(),
        context or _context(),
        limits=limits or _limits(),
        snapshot=snapshot if snapshot is not None else _snapshot(),
        evaluated_at=EVALUATED_AT,
    )


def _request() -> ApprovedExecutionRequest:
    intent = _intent()
    context = _execution_context()
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(transport: InMemoryDhanTransport) -> DhanBrokerAdapter:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "dhan", "NSE_EQ"
        ),
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None):
            from quantx.application.pending_recovery import PendingRecoveryRun
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=None)
    return runtime


def _evaluator(intent=None, context=None, limits=None, snapshot=None):
    def run(request) -> RiskResult:
        return PreTradeRiskEngine().evaluate_with_limits(
            intent or _intent(),
            context or _context(),
            limits=limits or _limits(),
            snapshot=snapshot if snapshot is not None else _snapshot(),
            evaluated_at=EVALUATED_AT,
        )

    return run


# Existing behavior regression.


def test_existing_approve_path_passes_with_limits() -> None:
    result = _evaluate()
    assert result.decision is RiskDecision.APPROVE


def test_existing_broker_constraint_rejection_preserved() -> None:
    context = _context(
        broker_constraints=(
            BrokerConstraint(
                "min-value", "broker minimum", minimum_order_value=Decimal("5000")
            ),
        )
    )
    result = _evaluate(_intent(quantity=Decimal("10")), context, _limits())
    assert result.decision is RiskDecision.REJECT
    assert "broker/venue minimum" in result.reason


def test_approval_required_becomes_reject_at_authoritative_boundary() -> None:
    result = _evaluate(_intent(approval_required=True))
    assert result.decision is RiskDecision.REJECT
    assert "explicit approval is required" in result.reason


# Order notional.


def _notional_limits() -> RiskLimits:
    return _limits(max_order_notional=Decimal("1000"))


def test_order_notional_below_limit_approves() -> None:
    result = _evaluate(_intent(quantity=Decimal("10")), limits=_notional_limits())
    assert result.decision is RiskDecision.APPROVE


def test_order_notional_exactly_at_limit_approves() -> None:
    result = _evaluate(_intent(quantity=Decimal("10")), limits=_notional_limits())
    assert result.decision is RiskDecision.APPROVE


def test_order_notional_above_limit_rejects() -> None:
    result = _evaluate(_intent(quantity=Decimal("11")), limits=_notional_limits())
    assert result.decision is RiskDecision.REJECT
    assert "ORDER_NOTIONAL_LIMIT_EXCEEDED" in result.reason


def test_order_notional_undeterminable_rejects() -> None:
    context = _context(reference_price=None)
    result = _evaluate(_intent(), context, _limits())
    assert result.decision is RiskDecision.REJECT


# Position exposure.


def test_position_below_limit_approves() -> None:
    result = _evaluate(limits=_limits(max_position_notional=Decimal("5000")))
    assert result.decision is RiskDecision.APPROVE


def test_position_exactly_at_limit_approves() -> None:
    snapshot = _snapshot(current_position_exposure=Decimal("4000"))
    result = _evaluate(limits=_limits(max_position_notional=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_position_above_limit_rejects() -> None:
    snapshot = _snapshot(current_position_exposure=Decimal("4500"))
    result = _evaluate(limits=_limits(max_position_notional=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "POSITION_EXPOSURE_LIMIT_EXCEEDED" in result.reason


def test_position_long_short_symmetry() -> None:
    snapshot = _snapshot(current_position_exposure=Decimal("-4500"))
    short = _evaluate(
        _intent(side=OrderSide.SELL),
        limits=_limits(max_position_notional=Decimal("5000")),
        snapshot=snapshot,
    )
    assert short.decision is RiskDecision.REJECT
    assert "POSITION_EXPOSURE_LIMIT_EXCEEDED" in short.reason
    reduce_short = _evaluate(
        _intent(side=OrderSide.BUY),
        limits=_limits(max_position_notional=Decimal("500")),
        snapshot=_snapshot(current_position_exposure=Decimal("-1400")),
    )
    assert reduce_short.decision is RiskDecision.APPROVE


def test_exposure_reducing_order_approves() -> None:
    snapshot = _snapshot(current_position_exposure=Decimal("4000"))
    result = _evaluate(
        _intent(side=OrderSide.SELL),
        limits=_limits(max_position_notional=Decimal("5000")),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.APPROVE


def test_crossing_through_zero_uses_signed_projection() -> None:
    snapshot = _snapshot(current_position_exposure=Decimal("500"))
    result = _evaluate(
        _intent(side=OrderSide.SELL),
        limits=_limits(max_position_notional=Decimal("5000")),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.APPROVE
    blocking = _evaluate(
        _intent(side=OrderSide.SELL),
        limits=_limits(max_position_notional=Decimal("400")),
        snapshot=snapshot,
    )
    assert blocking.decision is RiskDecision.REJECT


# Portfolio exposure.


def test_portfolio_below_limit_approves() -> None:
    snapshot = _snapshot(current_portfolio_exposure=Decimal("50000"))
    result = _evaluate(
        limits=_limits(
            max_portfolio_exposure=Decimal("100000"),
            max_instrument_concentration=None,
        ),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.APPROVE


def test_portfolio_exactly_at_limit_approves() -> None:
    snapshot = _snapshot(current_portfolio_exposure=Decimal("99000"))
    result = _evaluate(
        limits=_limits(
            max_portfolio_exposure=Decimal("100000"),
            max_instrument_concentration=None,
        ),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.APPROVE


def test_portfolio_above_limit_rejects() -> None:
    snapshot = _snapshot(current_portfolio_exposure=Decimal("200000"))
    result = _evaluate(
        limits=_limits(
            max_portfolio_exposure=Decimal("100000"),
            max_instrument_concentration=None,
        ),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.REJECT
    assert "PORTFOLIO_EXPOSURE_LIMIT_EXCEEDED" in result.reason


def test_portfolio_missing_exposure_fails_closed() -> None:
    snapshot = _snapshot(current_portfolio_exposure=None)
    result = _evaluate(
        limits=_limits(max_portfolio_exposure=Decimal("100000")), snapshot=snapshot
    )
    assert result.decision is RiskDecision.REJECT
    assert "RISK_VALUE_INVALID" in result.reason


# Instrument concentration.


def test_concentration_below_limit_approves() -> None:
    snapshot = _snapshot(
        current_instrument_exposure=Decimal("0"),
        current_portfolio_exposure=Decimal("10000"),
    )
    result = _evaluate(
        limits=_limits(max_instrument_concentration=Decimal("0.5")), snapshot=snapshot
    )
    assert result.decision is RiskDecision.APPROVE


def test_concentration_exactly_at_limit_approves() -> None:
    snapshot = _snapshot(
        current_instrument_exposure=Decimal("0"),
        current_portfolio_exposure=Decimal("1000"),
    )
    result = _evaluate(
        limits=_limits(max_instrument_concentration=Decimal("0.5")), snapshot=snapshot
    )
    assert result.decision is RiskDecision.APPROVE


def test_concentration_above_limit_rejects() -> None:
    snapshot = _snapshot(
        current_instrument_exposure=Decimal("500"),
        current_portfolio_exposure=Decimal("1000"),
    )
    result = _evaluate(
        limits=_limits(max_instrument_concentration=Decimal("0.4")), snapshot=snapshot
    )
    assert result.decision is RiskDecision.REJECT
    assert "INSTRUMENT_CONCENTRATION_LIMIT_EXCEEDED" in result.reason


def test_concentration_zero_denominator_fails_closed() -> None:
    snapshot = _snapshot(
        current_instrument_exposure=Decimal("-1000"),
        current_portfolio_exposure=Decimal("1000"),
    )
    result = _evaluate(
        _intent(side=OrderSide.SELL),
        limits=_limits(max_instrument_concentration=Decimal("0.5")),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.REJECT
    assert "RISK_STATE_INCONSISTENT" in result.reason


def test_concentration_missing_exposure_fails_closed() -> None:
    snapshot = _snapshot(current_instrument_exposure=None)
    result = _evaluate(
        limits=_limits(max_instrument_concentration=Decimal("0.5")), snapshot=snapshot
    )
    assert result.decision is RiskDecision.REJECT
    assert "RISK_VALUE_INVALID" in result.reason


# Daily loss.


def test_daily_loss_within_limit_approves() -> None:
    snapshot = _snapshot(daily_pnl=Decimal("-1000"))
    result = _evaluate(limits=_limits(max_daily_loss=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_daily_loss_exactly_at_limit_approves() -> None:
    snapshot = _snapshot(daily_pnl=Decimal("-5000"))
    result = _evaluate(limits=_limits(max_daily_loss=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_daily_loss_beyond_limit_rejects() -> None:
    snapshot = _snapshot(daily_pnl=Decimal("-5001"))
    result = _evaluate(limits=_limits(max_daily_loss=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "DAILY_LOSS_LIMIT_EXCEEDED" in result.reason


def test_daily_loss_missing_pnl_fails_closed() -> None:
    snapshot = _snapshot(daily_pnl=None)
    result = _evaluate(limits=_limits(max_daily_loss=Decimal("5000")), snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "RISK_VALUE_INVALID" in result.reason


def test_proposed_order_is_not_realized_pnl() -> None:
    snapshot = _snapshot(daily_pnl=Decimal("-4900"))
    result = _evaluate(
        _intent(quantity=Decimal("100")),
        limits=_limits(max_daily_loss=Decimal("5000"), max_order_notional=None),
        snapshot=snapshot,
    )
    assert result.decision is RiskDecision.APPROVE


# Drawdown.


def test_drawdown_within_limit_approves() -> None:
    snapshot = _snapshot(equity=Decimal("95000"), high_water_mark=Decimal("100000"))
    result = _evaluate(limits=_limits(max_drawdown=Decimal("0.2")), snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_drawdown_exactly_at_limit_approves() -> None:
    snapshot = _snapshot(equity=Decimal("80000"), high_water_mark=Decimal("100000"))
    result = _evaluate(limits=_limits(max_drawdown=Decimal("0.2")), snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_drawdown_beyond_limit_rejects() -> None:
    snapshot = _snapshot(equity=Decimal("79000"), high_water_mark=Decimal("100000"))
    result = _evaluate(limits=_limits(max_drawdown=Decimal("0.2")), snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "DRAWDOWN_LIMIT_EXCEEDED" in result.reason


def test_drawdown_invalid_high_water_mark_fails_closed() -> None:
    for bad_mark in (Decimal("0"), Decimal("-100")):
        snapshot = _snapshot(equity=Decimal("90000"), high_water_mark=bad_mark)
        result = _evaluate(limits=_limits(max_drawdown=Decimal("0.2")), snapshot=snapshot)
        assert result.decision is RiskDecision.REJECT
        assert "RISK_VALUE_INVALID" in result.reason


def test_drawdown_missing_inputs_fail_closed() -> None:
    for snapshot in (_snapshot(equity=None), _snapshot(high_water_mark=None)):
        result = _evaluate(limits=_limits(max_drawdown=Decimal("0.2")), snapshot=snapshot)
        assert result.decision is RiskDecision.REJECT
        assert "RISK_VALUE_INVALID" in result.reason


# Margin.


def test_margin_sufficient_approves() -> None:
    result = _evaluate()
    assert result.decision is RiskDecision.APPROVE


def test_margin_exact_boundary_approves() -> None:
    snapshot = _snapshot(available_margin=Decimal("1000"), required_margin=Decimal("1000"))
    result = _evaluate(snapshot=snapshot)
    assert result.decision is RiskDecision.APPROVE


def test_margin_insufficient_rejects() -> None:
    snapshot = _snapshot(available_margin=Decimal("999"), required_margin=Decimal("1000"))
    result = _evaluate(snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "MARGIN_INSUFFICIENT" in result.reason


def test_margin_missing_or_invalid_rejects() -> None:
    for snapshot in (
        _snapshot(available_margin=None),
        _snapshot(required_margin=None),
        _snapshot(required_margin=Decimal("-1")),
        _snapshot(available_margin=Decimal("NaN")),
        _snapshot(required_margin=Decimal("Infinity")),
    ):
        result = _evaluate(snapshot=snapshot)
        assert result.decision is RiskDecision.REJECT
        assert "MARGIN_INSUFFICIENT" in result.reason


# Fail-closed boundaries.


def test_missing_snapshot_rejects() -> None:
    result = PreTradeRiskEngine().evaluate_with_limits(
        _intent(),
        _context(),
        limits=_limits(),
        snapshot=None,
        evaluated_at=EVALUATED_AT,
    )
    assert result.decision is RiskDecision.REJECT
    assert "RISK_SNAPSHOT_MISSING" in result.reason


def test_stale_snapshot_rejects() -> None:
    snapshot = _snapshot(observed_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC))
    result = _evaluate(snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "RISK_SNAPSHOT_STALE" in result.reason


def test_future_snapshot_rejects() -> None:
    snapshot = _snapshot(observed_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC))
    result = _evaluate(snapshot=snapshot)
    assert result.decision is RiskDecision.REJECT
    assert "RISK_STATE_INCONSISTENT" in result.reason


def test_non_finite_snapshot_values_reject() -> None:
    for snapshot in (
        _snapshot(current_position_exposure=Decimal("NaN")),
        _snapshot(current_portfolio_exposure=Decimal("Infinity")),
        _snapshot(daily_pnl=Decimal("-Infinity")),
        _snapshot(equity=Decimal("NaN")),
        _snapshot(daily_pnl=True),
    ):
        result = _evaluate(snapshot=snapshot)
        assert result.decision is RiskDecision.REJECT


def test_invalid_configuration_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RiskLimits(max_order_notional=Decimal("-1"))
    with pytest.raises(ValueError, match="ratio"):
        RiskLimits(max_instrument_concentration=Decimal("1.5"))
    with pytest.raises(ValueError, match="ratio"):
        RiskLimits(max_drawdown=Decimal("-0.1"))
    with pytest.raises(ValueError, match="max_snapshot_age"):
        RiskLimits(max_snapshot_age=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="non-negative"):
        RiskLimits(max_daily_loss=True)


def test_naive_evaluated_at_rejects() -> None:
    result = PreTradeRiskEngine().evaluate_with_limits(
        _intent(),
        _context(),
        limits=_limits(),
        snapshot=_snapshot(),
        evaluated_at=datetime(2026, 1, 1, 9, 30),
    )
    assert result.decision is RiskDecision.REJECT
    assert "RISK_VALUE_INVALID" in result.reason


# Determinism and reason ordering.


def test_identical_inputs_give_identical_decisions() -> None:
    intent = _intent(quantity=Decimal("11"))
    limits = _limits(max_order_notional=Decimal("1000"), max_position_notional=Decimal("500"))
    snapshot = _snapshot(current_position_exposure=Decimal("4500"))
    first = _evaluate(intent, _context(), limits, snapshot)
    second = _evaluate(intent, _context(), limits, snapshot)
    assert first.decision is second.decision is RiskDecision.REJECT
    assert first.reason == second.reason
    assert "ORDER_NOTIONAL_LIMIT_EXCEEDED" in first.reason
    assert "POSITION_EXPOSURE_LIMIT_EXCEEDED" in first.reason
    assert first.reason.index("ORDER_NOTIONAL") < first.reason.index("POSITION_EXPOSURE")


# Enforcement integration.


def test_risk_rejection_blocks_gate_reservation_and_submit(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = ExecutionOrchestrator(
            unit_of_work=unit_of_work,
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
            live_risk_evaluator=_evaluator(limits=_limits(max_order_notional=Decimal("1"))),
        )
        request = _request()
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "ORDER_NOTIONAL_LIMIT_EXCEEDED" in result.reason
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as check_uow:
            decision = check_uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
            assert decision.operator_resolved is False
        from quantx.persistence.sqlite import SqliteReceiptRepository

        assert SqliteReceiptRepository(database).get_by_client_order(
            request.order.client_order_id
        ) is None
        assert unit_of_work.idempotency.get_operator_resolution(
            request.order.client_order_id, fingerprint
        ) is None
    finally:
        database.close()


def test_risk_approval_keeps_gate_reachable(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
            live_risk_evaluator=_evaluator(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert len(transport.submitted) == 1
    finally:
        database.close()


def test_upstream_approve_cannot_bypass_authoritative_risk(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
            live_risk_evaluator=_evaluator(
                limits=_limits(max_daily_loss=Decimal("1")),
                snapshot=_snapshot(daily_pnl=Decimal("-100")),
            ),
        )
        # The request carries an upstream APPROVE, yet the bound evaluator
        # rejects on current state; the submission must still be blocked.
        snapshot_request = _request()
        assert snapshot_request.risk_result.decision is RiskDecision.APPROVE
        result = orchestrator.execute(snapshot_request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "DAILY_LOSS_LIMIT_EXCEEDED" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_failing_risk_evaluator_fails_closed(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        def exploding(request) -> RiskResult:
            raise RuntimeError("risk snapshot unavailable")

        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
            live_risk_evaluator=exploding,
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "failed closed" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()
