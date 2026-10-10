"""R0-A regression tests: pending-resolution semantics and operator closure."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.application.evidence_refresh import (
    DefinitiveEvidencePolicy,
    ReconciliationEvidenceRefresher,
    RefreshPolicy,
)
from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.not_found_policy import (
    NotFoundResolutionPolicy,
    evaluate_not_found_resolution,
)
from quantx.application.operator_resolution import resolve_pending_operator
from quantx.application.pending_reconciliation import reconcile_pending_execution
from quantx.application.pending_recovery import PendingExecutionRecoveryRunner
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.execution.trading_gate import DurableTradingGate
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation import (
    BrokerOrderEvidence,
    BrokerOrderEvidenceStatus,
    OrderObservation,
)
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteReceiptRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.persistence.sqlite.schema import SCHEMA_VERSION
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport

CHECKED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


class UnknownProvider:
    """Broker lookup always fails: every outcome must stay UNKNOWN."""

    def __init__(self) -> None:
        self.order_calls = 0

    def fetch_broker_order(self, **kwargs):
        self.order_calls += 1
        return BrokerOrderEvidence.unknown("broker unavailable")

    def fetch_broker_position(self, **kwargs):
        return None

    def fetch_broker_account(self, **kwargs):
        return None


class NotFoundProvider:
    """Broker authoritatively reports absence on every lookup."""

    def __init__(self) -> None:
        self.order_calls = 0

    def fetch_broker_order(self, **kwargs):
        self.order_calls += 1
        return BrokerOrderEvidence.not_found("broker reports no such order")

    def fetch_broker_position(self, **kwargs):
        return None

    def fetch_broker_account(self, **kwargs):
        return None


class FoundProvider:
    """Broker returns one scripted observation, then UNKNOWN."""

    def __init__(self, observation: OrderObservation) -> None:
        self._observation = observation
        self.order_calls = 0

    def fetch_broker_order(self, **kwargs):
        self.order_calls += 1
        if self._observation is None:
            return BrokerOrderEvidence.unknown("no further observation")
        observation, self._observation = self._observation, None
        return BrokerOrderEvidence.found(observation)

    def fetch_broker_position(self, **kwargs):
        return None

    def fetch_broker_account(self, **kwargs):
        return None


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _request() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _observation(order_id, status, *, filled="0") -> OrderObservation:
    return OrderObservation(
        order_id,
        status,
        "2",
        filled,
        "dhan-1",
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
    )


def _fill(request) -> Fill:
    return Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal("2"),
        price=Decimal("100"),
        filled_at=CHECKED_AT,
    )


def _uow(tmp_path):
    database = SqliteDatabase(tmp_path / "quantx.db")
    return database, SqliteUnitOfWork(database)


def _reserve(unit_of_work, request) -> str:
    fingerprint = request_fingerprint(request)
    unit_of_work.idempotency.reserve_or_get(
        request.order.client_order_id,
        fingerprint,
        PendingExecutionContext.from_request(request, fingerprint),
    )
    return fingerprint


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


def _orchestrator(database, unit_of_work) -> ExecutionOrchestrator:
    """Orchestrator with approving India layers so the idempotency guard is reached.

    Without explicit session/rule evaluators, an India-LIVE request is blocked
    at the session-calendar check before the idempotency reservation is ever
    consulted, which would mask the operator-resolved guard under test here.
    """
    return ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
        application_runtime=_started_runtime(),
        india_rule_evaluator=_approving_india_rule_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )


def _approving_india_rule_evaluator():
    """India rule layer is not under test here; approve to reach the guard."""

    def approve(request):
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
    """India session layer is not under test here; approve to reach the guard."""

    def allow(request):
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


def test_unknown_evidence_is_not_not_found(tmp_path) -> None:
    """A: timeout/transport failure stays UNKNOWN and PENDING."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        provider = UnknownProvider()

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=None,
            broker_order=None,
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert provider.order_calls >= 1
        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.operator_resolved is False
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_unknown_status_is_distinct_from_not_found() -> None:
    """A: the evidence vocabulary keeps UNKNOWN and NOT_FOUND disjoint."""
    unknown = BrokerOrderEvidence.unknown("timeout")
    assert unknown.status is BrokerOrderEvidenceStatus.UNKNOWN
    assert unknown.status is not BrokerOrderEvidenceStatus.NOT_FOUND
    assert unknown.observation is None
    with pytest.raises(ValueError, match="requires an observation"):
        BrokerOrderEvidence(status=BrokerOrderEvidenceStatus.FOUND)
    with pytest.raises(ValueError, match="must not carry an observation"):
        BrokerOrderEvidence(
            status=BrokerOrderEvidenceStatus.NOT_FOUND,
            observation=_observation(uuid4(), OrderLifecycleStatus.UNKNOWN),
        )


def test_immediate_not_found_does_not_resolve(tmp_path) -> None:
    """B: one immediate NOT_FOUND resolves nothing; PENDING, no receipt."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        provider = NotFoundProvider()

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=None,
            broker_order=None,
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert provider.order_calls >= 1
        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
    finally:
        database.close()


def test_not_found_policy_requires_age_and_secondary() -> None:
    """B/C: eligibility needs authority, elapsed wait, and secondary proof."""
    policy = NotFoundResolutionPolicy(
        min_pending_age=timedelta(hours=1), require_secondary_absence=True
    )
    fresh = evaluate_not_found_resolution(
        evidence_status=BrokerOrderEvidenceStatus.NOT_FOUND,
        pending_age=timedelta(minutes=5),
        secondary_absence_confirmed=True,
        policy=policy,
    )
    assert fresh.eligible is False
    assert "pending age" in fresh.reason

    no_secondary = evaluate_not_found_resolution(
        evidence_status=BrokerOrderEvidenceStatus.NOT_FOUND,
        pending_age=timedelta(hours=2),
        secondary_absence_confirmed=None,
        policy=policy,
    )
    assert no_secondary.eligible is False
    assert "secondary" in no_secondary.reason

    denied = evaluate_not_found_resolution(
        evidence_status=BrokerOrderEvidenceStatus.NOT_FOUND,
        pending_age=timedelta(hours=2),
        secondary_absence_confirmed=False,
        policy=policy,
    )
    assert denied.eligible is False

    ambiguous = evaluate_not_found_resolution(
        evidence_status=BrokerOrderEvidenceStatus.UNKNOWN,
        pending_age=timedelta(hours=2),
        secondary_absence_confirmed=True,
        policy=policy,
    )
    assert ambiguous.eligible is False

    eligible = evaluate_not_found_resolution(
        evidence_status=BrokerOrderEvidenceStatus.NOT_FOUND,
        pending_age=timedelta(hours=2),
        secondary_absence_confirmed=True,
        policy=policy,
    )
    assert eligible.eligible is True


def test_not_found_without_secondary_stays_pending(tmp_path) -> None:
    """C: NOT_FOUND without secondary evidence never auto-resolves."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=None,
            broker_order=None,
            provider=NotFoundProvider(),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_definitive_evidence_still_resolves(tmp_path) -> None:
    """D: authoritative broker evidence completes receipt + idempotency."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        broker_order = _observation(order_id, OrderLifecycleStatus.FILLED, filled="2")

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=FoundProvider(broker_order),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert outcome.definitive
        persisted = SqliteReceiptRepository(database).get_by_client_order(order_id)
        assert persisted is not None
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id == persisted.receipt_id
        assert decision.reservation_pending is False
    finally:
        database.close()


def test_operator_resolution_requires_identity(tmp_path) -> None:
    """E: empty operator identity is rejected before any state change."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        fingerprint = _reserve(unit_of_work, request)
        for bad_identity in ("", "   "):
            with pytest.raises(ValueError, match="operator identity"):
                resolve_pending_operator(
                    unit_of_work=unit_of_work,
                    client_order_id=request.order.client_order_id,
                    request_fingerprint=fingerprint,
                    operator_id=bad_identity,
                    reason="broker never received this",
                    resolved_at=RESOLVED_AT,
                )
        decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
        assert decision.reservation_pending is True
    finally:
        database.close()


def test_operator_resolution_requires_reason(tmp_path) -> None:
    """F: empty reason is rejected before any state change."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        fingerprint = _reserve(unit_of_work, request)
        for bad_reason in ("", "   "):
            with pytest.raises(ValueError, match="reason"):
                resolve_pending_operator(
                    unit_of_work=unit_of_work,
                    client_order_id=request.order.client_order_id,
                    request_fingerprint=fingerprint,
                    operator_id="ops-1",
                    reason=bad_reason,
                    resolved_at=RESOLVED_AT,
                )
        decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
        assert decision.reservation_pending is True
    finally:
        database.close()


def test_operator_resolution_requires_matching_fingerprint(tmp_path) -> None:
    """G: wrong fingerprint is rejected; reservation stays PENDING."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        fingerprint = _reserve(unit_of_work, request)
        with pytest.raises(ValueError, match="different request"):
            resolve_pending_operator(
                unit_of_work=unit_of_work,
                client_order_id=request.order.client_order_id,
                request_fingerprint="wrong-fingerprint",
                operator_id="ops-1",
                reason="broker never received this",
                resolved_at=RESOLVED_AT,
            )
        decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.operator_resolved is False
    finally:
        database.close()


def test_operator_resolution_rejects_completed(tmp_path) -> None:
    """H: a completed reservation cannot be operator-resolved."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        unit_of_work.idempotency.complete(order_id, fingerprint, uuid4())
        with pytest.raises(ValueError, match="completed"):
            resolve_pending_operator(
                unit_of_work=unit_of_work,
                client_order_id=order_id,
                request_fingerprint=fingerprint,
                operator_id="ops-1",
                reason="broker never received this",
                resolved_at=RESOLVED_AT,
            )
    finally:
        database.close()


def test_operator_resolution_rejects_nonexistent(tmp_path) -> None:
    """H: a nonexistent reservation cannot be operator-resolved."""
    database, unit_of_work = _uow(tmp_path)
    try:
        with pytest.raises(ValueError, match="unreserved"):
            resolve_pending_operator(
                unit_of_work=unit_of_work,
                client_order_id=uuid4(),
                request_fingerprint="fp-missing",
                operator_id="ops-1",
                reason="broker never received this",
                resolved_at=RESOLVED_AT,
            )
    finally:
        database.close()


def test_operator_resolution_is_durable_across_restart(tmp_path) -> None:
    """I: the audit record survives process restart."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(SqliteUnitOfWork(database), request)
        record = resolve_pending_operator(
            unit_of_work=SqliteUnitOfWork(database),
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="desk confirmed no broker order",
            resolved_at=RESOLVED_AT,
            evidence_reference="dhan lookup 2026-01-02: no such order",
        )
        assert record.operator_id == "ops-1"
    finally:
        database.close()

    reopened = SqliteDatabase(path)
    try:
        stored = SqliteUnitOfWork(reopened).idempotency.get_operator_resolution(
            request.order.client_order_id, fingerprint
        )
        assert stored is not None
        assert stored.operator_id == "ops-1"
        assert stored.reason == "desk confirmed no broker order"
        assert stored.resolved_at == RESOLVED_AT
        assert stored.evidence_reference == "dhan lookup 2026-01-02: no such order"
        decision = SqliteUnitOfWork(reopened).idempotency.check(
            request.order.client_order_id, fingerprint
        )
        assert decision.operator_resolved is True
        assert decision.reservation_pending is False
    finally:
        reopened.close()


def test_operator_resolution_creates_no_receipt(tmp_path) -> None:
    """J: resolution writes audit history, never an execution receipt."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_operator_resolved_blocks_implicit_resubmission(tmp_path) -> None:
    """K: normal execute() on a resolved id must not submit."""
    transport = InMemoryDhanTransport(response_status="PENDING")
    adapter = _adapter(transport)
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=request.order.client_order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        result = _orchestrator(database, unit_of_work).execute(request, broker=adapter)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert transport.submitted == ()
    finally:
        database.close()


def test_second_resolution_fails_closed_preserving_history(tmp_path) -> None:
    """L: repeat resolution never overwrites the immutable record."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        first = resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="first reason",
            resolved_at=RESOLVED_AT,
        )
        with pytest.raises(ValueError, match="already operator-resolved"):
            resolve_pending_operator(
                unit_of_work=unit_of_work,
                client_order_id=order_id,
                request_fingerprint=fingerprint,
                operator_id="ops-2",
                reason="second reason",
                resolved_at=datetime(2026, 1, 3, 12, 0, tzinfo=UTC),
            )
        stored = unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint)
        assert stored == first
        assert stored is not None
        assert stored.operator_id == "ops-1"
        assert stored.reason == "first reason"
        assert stored.resolved_at == RESOLVED_AT
    finally:
        database.close()


def test_recovery_never_invokes_operator_resolution(tmp_path) -> None:
    """M: recovery leaves PENDING and writes no resolution record."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        run = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=lambda _: UnknownProvider(),
        ).run(checked_at=CHECKED_AT)

        assert run.attempted == 1
        assert run.resolved == 0
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.operator_resolved is False
        assert unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint) is None
    finally:
        database.close()


def test_no_fake_terminal_execution_state(tmp_path) -> None:
    """N: resolution creates no FILLED/CANCELLED/REJECTED/UNKNOWN receipt."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        repository = SqliteReceiptRepository(database)
        assert repository.get_by_client_order(order_id) is None
        assert repository.list_by_correlation_id(request.correlation_id) == ()
    finally:
        database.close()


def test_no_implicit_retry_after_resolution(tmp_path) -> None:
    """O: repeated executes after resolution never submit or retry."""
    transport = InMemoryDhanTransport(response_status="PENDING")
    adapter = _adapter(transport)
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=request.order.client_order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        orchestrator = _orchestrator(database, unit_of_work)
        first = orchestrator.execute(request, broker=adapter)
        second = orchestrator.execute(request, broker=adapter)

        assert first.status is ExecutionDispatchStatus.BLOCKED
        assert second.status is ExecutionDispatchStatus.BLOCKED
        assert transport.submitted == ()
    finally:
        database.close()


def _refresh_receipt(order_id) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=CHECKED_AT,
        broker_order_id="dhan-1",
        order_id=order_id,
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )


def test_eligible_policy_verdict_surfaces_without_resolving(tmp_path) -> None:
    """Policy wiring: an eligible verdict is informational, never resolving."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        refresher = ReconciliationEvidenceRefresher(
            refresh_policy=RefreshPolicy(max_attempts=1),
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )
        outcome = refresher.refresh(
            _refresh_receipt(order_id),
            local_order=None,
            broker_order=None,
            checked_at=CHECKED_AT,
            provider=NotFoundProvider(),
            pending_age=timedelta(hours=2),
            secondary_absence_confirmed=True,
        )

        assert not outcome.definitive
        assert outcome.not_found_eligibility is not None
        assert outcome.not_found_eligibility.eligible is True
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
        assert decision.operator_resolved is False
        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        assert unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint) is None
    finally:
        database.close()


def test_reconcile_path_surfaces_ineligible_verdict(tmp_path) -> None:
    """Policy wiring: the reconcile entry point exposes eligibility too."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=None,
            broker_order=None,
            provider=NotFoundProvider(),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert not outcome.definitive
        assert outcome.not_found_eligibility is not None
        assert outcome.not_found_eligibility.eligible is False
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
    finally:
        database.close()


def test_sqlite_v3_to_current_migration_preserves_reservations(tmp_path) -> None:
    """Migration is additive: pending/completed rows survive, none resolve."""
    path = tmp_path / "quantx.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        raw.execute(
            "CREATE TABLE idempotency_reservations (client_order_id TEXT PRIMARY KEY, "
            "fingerprint TEXT NOT NULL, receipt_id TEXT NULL, created_at TEXT NOT NULL, "
            "completed_at TEXT NULL, pending_context_json TEXT NULL)"
        )
        raw.execute(
            "CREATE TABLE receipts (receipt_id TEXT PRIMARY KEY, "
            "client_order_id TEXT NOT NULL, payload TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        request = _request()
        fingerprint = request_fingerprint(request)
        context_json = PendingExecutionContext.from_request(request, fingerprint).to_json()
        raw.execute(
            "INSERT INTO idempotency_reservations VALUES (?,?,?,?,?,?)",
            (
                str(request.order.client_order_id),
                fingerprint,
                None,
                "2026-01-01T00:00:00+00:00",
                None,
                context_json,
            ),
        )
        completed_id = uuid4()
        completed_receipt = uuid4()
        raw.execute(
            "INSERT INTO idempotency_reservations VALUES (?,?,?,?,?,?)",
            (
                str(completed_id),
                "fp-done",
                str(completed_receipt),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T01:00:00+00:00",
                None,
            ),
        )
        raw.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (3, ?)",
            ("2026-01-01T00:00:00+00:00",),
        )
        raw.commit()
    finally:
        raw.close()

    database = SqliteDatabase(path)
    try:
        version = database.connection().execute("SELECT version FROM schema_version")
        assert version.fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "operator_resolutions" in tables
        count = database.connection().execute("SELECT COUNT(*) FROM operator_resolutions")
        assert count.fetchone()[0] == 0

        store = SqliteUnitOfWork(database).idempotency
        pending = store.check(request.order.client_order_id, fingerprint)
        assert pending.reservation_pending is True
        assert pending.operator_resolved is False
        done = store.check(completed_id, "fp-done")
        assert done.existing_receipt_id == completed_receipt
        assert done.reservation_pending is False
        assert done.operator_resolved is False
    finally:
        database.close()

    reopened = SqliteDatabase(path)
    try:
        version = reopened.connection().execute("SELECT version FROM schema_version")
        assert version.fetchone()[0] == SCHEMA_VERSION
        pending = SqliteUnitOfWork(reopened).idempotency.check(
            request.order.client_order_id, fingerprint
        )
        assert pending.reservation_pending is True
    finally:
        reopened.close()


def test_failed_resolution_writes_no_audit_record(tmp_path) -> None:
    """Atomicity: rejected resolution attempts leave no audit residue."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        with pytest.raises(ValueError, match="different request"):
            resolve_pending_operator(
                unit_of_work=unit_of_work,
                client_order_id=order_id,
                request_fingerprint="wrong-fingerprint",
                operator_id="ops-1",
                reason="broker never received this",
                resolved_at=RESOLVED_AT,
            )
        count = database.connection().execute("SELECT COUNT(*) FROM operator_resolutions")
        assert count.fetchone()[0] == 0
        assert unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint) is None
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
    finally:
        database.close()


def test_recovery_skips_operator_resolved(tmp_path) -> None:
    """Resolved reservations never re-enter the recovery workflow."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        run = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=lambda _: UnknownProvider(),
        ).run(checked_at=CHECKED_AT)

        assert run.attempted == 0
        assert run.failed == 0
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.operator_resolved is True
        assert decision.reservation_pending is False
    finally:
        database.close()


def test_complete_and_resolve_pending_reject_resolved(tmp_path) -> None:
    """No completion path can reopen an operator-resolved reservation."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        with pytest.raises(ValueError, match="operator-resolved"):
            unit_of_work.idempotency.complete(order_id, fingerprint, uuid4())
        with pytest.raises(ValueError, match="operator-resolved"):
            unit_of_work.idempotency.resolve_pending(order_id, fingerprint, uuid4())
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.operator_resolved is True
        assert decision.existing_receipt_id is None
    finally:
        database.close()
