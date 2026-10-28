"""R1-A regression tests: deterministic LIVE risk invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.live_risk import LivePreTradeRiskEvaluator, LiveRiskEvaluationInputs
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import Clock, FixedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.instrument_registry import InstrumentResolution
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
    LiveRiskLimitsError,
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
)
from quantx.domain.value_objects import Money, ProductCode
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.trading_gate import DurableTradingGate
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.market_checks import india_market_policy
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from tests.unit._execution_request_proofs import approved_request, policy_verifier

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
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )


def _intent(**overrides) -> TradeIntent:
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "required_margin": Decimal("1000"),
        "required_capabilities": frozenset({"ORDER_SUBMISSION"}),
        "execution_context": _execution_context(),
        "product": ProductCode("CNC"),
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
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=ProductCode("CNC"),
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
                DhanInstrumentRef("1333", "NSE_EQ", "TCS"),
            )
        },
        _transport=transport,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
        _product_map={"CNC": "CNC"},
    )


def _approving_india_evaluator():
    """India layer is not under test here; approve explicitly to reach it."""

    def approve(request) -> IndiaRuleResult:
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "india compatibility approved for test",
            rule_set_version="test-b3",
            provenance="test-b3",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return approve


def _approving_india_session_evaluator():
    """B4 boundary is not under test here; provide explicit session evidence."""

    def allow(request) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            session_id="regular",
            granted_permissions=frozenset({IndiaSessionPermission.ORDER_SUBMISSION}),
            calendar_evaluated=True,
        )

    return allow


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


def _live_evaluation_inputs(**overrides) -> LiveRiskEvaluationInputs:
    values: dict = {
        "intent": _intent(),
        "context": _context(),
        "snapshot": _snapshot(),
        "claimed_evaluated_at": EVALUATED_AT,
    }
    values.update(overrides)
    return LiveRiskEvaluationInputs(**values)


def _live_pre_trade_evaluator(
    limits: RiskLimits,
    inputs: LiveRiskEvaluationInputs | None = None,
    *,
    clock: Clock | None = None,
) -> LivePreTradeRiskEvaluator:
    def inputs_for_request(request: ApprovedExecutionRequest) -> LiveRiskEvaluationInputs:
        return inputs if inputs is not None else _live_evaluation_inputs()

    return LivePreTradeRiskEvaluator(
        engine=PreTradeRiskEngine(),
        limits=limits,
        inputs_for_request=inputs_for_request,
        clock=clock if clock is not None else FixedClock(EVALUATED_AT),
    )


# Existing behavior regression.


def test_existing_approve_path_passes_with_limits() -> None:
    result = _evaluate()
    assert result.decision is RiskDecision.APPROVE


def test_existing_broker_constraint_rejection_preserved() -> None:
    context = _context(
        broker_constraints=(
            BrokerConstraint("min-value", "broker minimum", minimum_order_value=Decimal("5000")),
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
    result = _evaluate(limits=_limits(max_portfolio_exposure=Decimal("100000")), snapshot=snapshot)
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


def test_arbitrary_risk_callback_blocks_before_reservation_and_submit(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = ExecutionOrchestrator(
            unit_of_work=unit_of_work,
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            application_runtime=_started_runtime(),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=_evaluator(limits=_limits(max_order_notional=Decimal("1"))),
            policy_verifier=policy_verifier(),
        )
        request = _request()
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "application-owned risk evaluator" in result.reason
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as check_uow:
            decision = check_uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
            assert decision.operator_resolved is False
        from quantx.persistence.sqlite import SqliteReceiptRepository

        assert (
            SqliteReceiptRepository(database).get_by_client_order(request.order.client_order_id)
            is None
        )
        assert (
            unit_of_work.idempotency.get_operator_resolution(
                request.order.client_order_id, fingerprint
            )
            is None
        )
    finally:
        database.close()


def test_arbitrary_risk_approval_cannot_reach_live_gate(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            application_runtime=_started_runtime(),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=_evaluator(),
            policy_verifier=policy_verifier(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "application-owned risk evaluator" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_upstream_approve_cannot_bypass_authoritative_risk(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            application_runtime=_started_runtime(),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=_evaluator(
                limits=_limits(max_daily_loss=Decimal("1")),
                snapshot=_snapshot(daily_pnl=Decimal("-100")),
            ),
            policy_verifier=policy_verifier(),
        )
        # The request carries an upstream APPROVE, yet the bound evaluator
        # rejects on current state; the submission must still be blocked.
        snapshot_request = _request()
        assert snapshot_request.risk_result.decision is RiskDecision.APPROVE
        result = orchestrator.execute(snapshot_request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "application-owned risk evaluator" in result.reason
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
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            application_runtime=_started_runtime(),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=exploding,
            policy_verifier=policy_verifier(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "application-owned risk evaluator" in result.reason
        # The callback is rejected before invocation, so no arbitrary error is surfaced.
        assert "risk snapshot unavailable" not in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


# LivePreTradeRiskEvaluator composition boundary.


def test_live_pre_trade_evaluator_requires_explicit_limits() -> None:
    with pytest.raises(LiveRiskLimitsError):
        _live_pre_trade_evaluator(RiskLimits())


def test_live_pre_trade_evaluator_approves_within_limits() -> None:
    evaluator = _live_pre_trade_evaluator(_limits())

    result = evaluator(_request())

    assert result.decision is RiskDecision.APPROVE


def test_live_pre_trade_evaluator_rejects_order_notional_over_limit() -> None:
    evaluator = _live_pre_trade_evaluator(_limits(max_order_notional=Decimal("100")))

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "ORDER_NOTIONAL_LIMIT_EXCEEDED" in result.reason


def test_live_pre_trade_evaluator_rejects_position_notional_over_limit() -> None:
    evaluator = _live_pre_trade_evaluator(_limits(max_position_notional=Decimal("100")))

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "POSITION_EXPOSURE_LIMIT_EXCEEDED" in result.reason


def test_live_pre_trade_evaluator_rejects_daily_loss_over_limit() -> None:
    inputs = _live_evaluation_inputs(snapshot=_snapshot(daily_pnl=Decimal("-100")))
    evaluator = _live_pre_trade_evaluator(_limits(max_daily_loss=Decimal("1")), inputs)

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "DAILY_LOSS_LIMIT_EXCEEDED" in result.reason


def test_live_pre_trade_evaluator_rejects_stale_snapshot() -> None:
    snapshot = _snapshot(observed_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC))
    inputs = _live_evaluation_inputs(snapshot=snapshot)
    evaluator = _live_pre_trade_evaluator(
        _limits(max_snapshot_age=timedelta(minutes=1)),
        inputs,
    )

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "RISK_SNAPSHOT_STALE" in result.reason


def test_live_pre_trade_evaluator_uses_the_trusted_clock_not_the_provider_claim() -> None:
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=datetime(2020, 1, 1, 9, 29, tzinfo=UTC)),
        claimed_evaluated_at=datetime(2020, 1, 1, 9, 30, tzinfo=UTC),
    )
    evaluator = _live_pre_trade_evaluator(
        _limits(max_snapshot_age=timedelta(minutes=5)),
        inputs,
    )

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_CLAIM_OUT_OF_TOLERANCE")


def test_live_pre_trade_evaluator_rejects_wrong_inputs_type() -> None:
    evaluator = LivePreTradeRiskEvaluator(
        engine=PreTradeRiskEngine(),
        limits=_limits(),
        inputs_for_request=lambda request: cast(LiveRiskEvaluationInputs, object()),
        clock=FixedClock(EVALUATED_AT),
    )

    with pytest.raises(TypeError, match="LIVE risk evaluation inputs"):
        evaluator(_request())


def test_live_pre_trade_evaluator_keeps_validated_copy_after_source_mutation() -> None:
    limits = _limits(max_order_notional=Decimal("100"))
    evaluator = _live_pre_trade_evaluator(limits)
    object.__setattr__(limits, "max_order_notional", Decimal("1000000"))

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "ORDER_NOTIONAL_LIMIT_EXCEEDED" in result.reason


# Trusted clock (slice B): the provider timestamp is a claim, not time authority.


class _RaisingClock(Clock):
    def now(self) -> datetime:
        raise RuntimeError("internal broker clock detail")


class _NaiveClock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 9, 30)


class _UnusableReadingClock(Clock):
    def now(self) -> datetime:
        return cast(datetime, "2026-01-01T09:30:00+00:00")


class _DriftingClock(Clock):
    """Returns the intended instant once, then an hour later."""

    def __init__(self) -> None:
        self.reads = 0

    def now(self) -> datetime:
        self.reads += 1
        if self.reads == 1:
            return EVALUATED_AT
        return EVALUATED_AT + timedelta(hours=1)


def test_live_pre_trade_evaluator_approves_a_fresh_snapshot_with_an_aligned_claim() -> None:
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=EVALUATED_AT - timedelta(seconds=30)),
        claimed_evaluated_at=EVALUATED_AT,
    )

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.APPROVE


def test_live_pre_trade_evaluator_rejects_a_claim_close_to_an_hours_old_observed_at() -> None:
    observed_at = EVALUATED_AT - timedelta(hours=6)
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=observed_at),
        claimed_evaluated_at=observed_at + timedelta(seconds=1),
    )

    result = _live_pre_trade_evaluator(
        _limits(max_snapshot_age=timedelta(minutes=5)),
        inputs,
    )(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_CLAIM_OUT_OF_TOLERANCE")


def test_live_pre_trade_evaluator_cannot_move_freshness_with_a_claim_inside_tolerance() -> None:
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=EVALUATED_AT - timedelta(hours=6)),
        claimed_evaluated_at=EVALUATED_AT - timedelta(seconds=2),
    )

    result = _live_pre_trade_evaluator(
        _limits(max_snapshot_age=timedelta(minutes=5)),
        inputs,
    )(_request())

    assert result.decision is RiskDecision.REJECT
    assert "RISK_SNAPSHOT_STALE" in result.reason
    assert "LIVE_CLOCK" not in result.reason


def test_live_pre_trade_evaluator_keeps_a_short_freshness_budget_on_trusted_time() -> None:
    """A tolerated claim cannot recycle two seconds of an already-stale snapshot."""
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=EVALUATED_AT - timedelta(seconds=6)),
        claimed_evaluated_at=EVALUATED_AT - timedelta(seconds=4),
    )

    result = _live_pre_trade_evaluator(
        _limits(max_snapshot_age=timedelta(seconds=3)),
        inputs,
    )(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("RISK_SNAPSHOT_STALE")


def test_live_pre_trade_evaluator_accepts_a_claim_exactly_at_the_tolerance() -> None:
    inputs = _live_evaluation_inputs(
        claimed_evaluated_at=EVALUATED_AT - timedelta(seconds=5),
    )

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.APPROVE


def test_live_pre_trade_evaluator_rejects_a_claim_beyond_the_tolerance() -> None:
    inputs = _live_evaluation_inputs(
        claimed_evaluated_at=EVALUATED_AT - timedelta(seconds=5, microseconds=1),
    )

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_CLAIM_OUT_OF_TOLERANCE")


def test_live_pre_trade_evaluator_rejects_a_naive_claim() -> None:
    inputs = _live_evaluation_inputs(claimed_evaluated_at=datetime(2026, 1, 1, 9, 30))

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_CLAIM_INVALID")


def test_live_pre_trade_evaluator_rejects_a_non_datetime_claim() -> None:
    for claim in ("2026-01-01T09:30:00+00:00", 1767263400, True):
        inputs = _live_evaluation_inputs(claimed_evaluated_at=cast(datetime, claim))

        result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

        assert result.decision is RiskDecision.REJECT
        assert result.reason.startswith("LIVE_CLOCK_CLAIM_INVALID")


def test_live_pre_trade_evaluator_accepts_a_claim_in_another_timezone() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    claim = EVALUATED_AT.astimezone(ist)
    assert claim.utcoffset() == timedelta(hours=5, minutes=30)
    inputs = _live_evaluation_inputs(claimed_evaluated_at=claim)

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.APPROVE


def test_live_pre_trade_evaluator_rejects_an_unreadable_clock() -> None:
    result = _live_pre_trade_evaluator(_limits(), clock=_RaisingClock())(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_UNAVAILABLE")
    assert "internal broker clock detail" not in result.reason


def test_live_pre_trade_evaluator_rejects_a_naive_clock_reading() -> None:
    result = _live_pre_trade_evaluator(_limits(), clock=_NaiveClock())(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_INVALID")


def test_live_pre_trade_evaluator_rejects_an_unusable_clock_reading() -> None:
    result = _live_pre_trade_evaluator(_limits(), clock=_UnusableReadingClock())(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.reason.startswith("LIVE_CLOCK_INVALID")


def test_live_pre_trade_evaluator_reads_the_clock_once_per_evaluation() -> None:
    clock = _DriftingClock()
    inputs = _live_evaluation_inputs(
        snapshot=_snapshot(observed_at=EVALUATED_AT - timedelta(seconds=30)),
        claimed_evaluated_at=EVALUATED_AT,
    )

    result = _live_pre_trade_evaluator(_limits(), inputs, clock=clock)(_request())

    assert result.decision is RiskDecision.APPROVE
    assert clock.reads == 1


def test_live_pre_trade_evaluator_rejections_keep_the_resolved_instrument() -> None:
    resolution = InstrumentResolution(
        instrument=_instrument(),
        instrument_rule_version="india-products-v1",
        instrument_rule_effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        resolved_at=datetime(2025, 12, 1, tzinfo=UTC),
    )
    context = RiskContext(
        _instrument(),
        _financial(),
        reference_price=Decimal("100"),
        instrument_resolution=resolution,
    )
    inputs = _live_evaluation_inputs(
        context=context,
        claimed_evaluated_at=datetime(2020, 1, 1, 9, 30, tzinfo=UTC),
    )

    result = _live_pre_trade_evaluator(_limits(), inputs)(_request())

    assert result.decision is RiskDecision.REJECT
    assert result.instrument_resolution is resolution


@pytest.mark.parametrize(
    "intent_overrides",
    [
        {"instrument": InstrumentId("NSE", "INFY")},
        {"side": OrderSide.SELL},
        {"quantity": Decimal("9")},
        {"order_type": OrderType.LIMIT, "limit_price": Decimal("101")},
        {"required_capabilities": frozenset()},
        {"product": ProductCode("MIS")},
        {
            "execution_context": replace(
                _execution_context(), account_id=AccountId("foreign-account")
            )
        },
    ],
    ids=[
        "instrument",
        "side",
        "quantity",
        "order-type-and-price",
        "capabilities",
        "product",
        "account-context",
    ],
)
def test_live_pretrade_evaluator_rejects_intent_that_differs_from_request(intent_overrides) -> None:
    inputs = _live_evaluation_inputs(intent=_intent(**intent_overrides))
    evaluator = _live_pre_trade_evaluator(_limits(), inputs, clock=FixedClock(EVALUATED_AT))

    result = evaluator(_request())

    assert result.decision is RiskDecision.REJECT
    assert "LIVE_RISK_REQUEST_MISMATCH" in result.reason
