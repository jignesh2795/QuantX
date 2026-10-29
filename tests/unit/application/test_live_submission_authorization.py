"""Admission-boundary regressions for the LIVE submission path (#267).

The transactional LIVE path used to be reachable directly with a request, a
broker, and a unit of work, skipping every admission check in
``ExecutionOrchestrator.execute``. These tests pin the closed boundary:
the transactional path refuses to reserve or submit unless it is handed the
single-use authorization that ``execute`` mints only after every LIVE
admission check succeeded for the exact same request.

Safety invariants tested (deterministic fakes; no live broker calls,
credentials, or real orders):
- The transactional path without a valid authorization is rejected before
  any durable reservation or broker submission.
- A missing, forged, foreign, tampered, mismatched, or replayed
  authorization cannot authorize any request.
- Public LIVE dispatch stays blocked when authoritative admission evidence
  is unavailable, with zero reservation and zero broker submissions.
- Non-LIVE execution and preflight rejection behavior are unchanged.
- No alternative internal or public route reaches broker submission
  without the same authorization requirement.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.live_submission_capability import (
    LiveSubmissionAuthorization,
    LiveSubmissionAuthorizationError,
    LiveSubmissionAuthorizer,
)
from quantx.application.pending_recovery import PendingRecoveryRun
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.trading_gate import (
    DurableTradingGate,
    InMemoryTradingGateStateStore,
    TradingGate,
)
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.market_checks import india_market_policy
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
    CapabilitySet,
)
from quantx.persistence import ReceiptRepository, UnitOfWork
from tests.unit._execution_request_proofs import approved_request, policy_verifier

# ---------------------------------------------------------------------------
# Shared fixtures / factory helpers
# ---------------------------------------------------------------------------

_ACCOUNT_ID = AccountId("acct-qx267")
_CONNECTION_ID = BrokerConnectionId("conn-qx267")
_FOREIGN_ACCOUNT_ID = AccountId("acct-foreign")


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


def _request(*, execution_mode: ExecutionMode = ExecutionMode.LIVE) -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=_ACCOUNT_ID,
        portfolio_id=PortfolioId("portfolio-qx267"),
        deployment_id=StrategyDeploymentId("deploy-qx267"),
        market=instrument.market,
        broker_connection_id=_CONNECTION_ID,
        execution_mode=execution_mode,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
        product=ProductCode("CNC"),
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=ProductCode("CNC"),
    )


def _valid_receipt(request: ApprovedExecutionRequest) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )


class _FakeReceiptRepository(ReceiptRepository):
    def __init__(self) -> None:
        self._receipts: dict = {}

    def save(self, receipt: ExecutionReceipt) -> None:
        self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id):
        return self._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id):
        for receipt in self._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None


class _FakeUnitOfWork(UnitOfWork):
    def __init__(self, store: InMemoryIdempotencyStore | None = None) -> None:
        self._store = store or InMemoryIdempotencyStore()
        self._repository = _FakeReceiptRepository()
        self.committed = False

    @property
    def idempotency(self):
        return self._store

    @property
    def receipts(self):
        return self._repository

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.commit()


class _FakeSubmissionQuarantine:
    def __init__(self) -> None:
        self._observations: dict = {}

    def record(self, observation) -> None:
        self._observations[observation.observation_id] = observation

    def get(self, observation_id):
        return self._observations.get(observation_id)

    def list_all(self):
        return tuple(self._observations.values())


class _FakeBroker:
    """Deterministic broker fake that records every submit attempt."""

    def __init__(
        self,
        receipt_factory=None,
        *,
        submit_error: Exception | None = None,
        account_id: AccountId = _ACCOUNT_ID,
    ) -> None:
        self._receipt_factory = receipt_factory or _valid_receipt
        self._submit_error = submit_error
        self._connection = BrokerConnectionRef(account_id, _CONNECTION_ID, "fake", "NSE")
        self._instrument = _instrument()
        self.submit_calls = 0

    @property
    def connection(self):
        return self._connection

    def health(self):
        return True

    def capabilities(self):
        return CapabilitySet(frozenset({BrokerCapability.ORDER_SUBMISSION}))

    def instrument(self, instrument_id):
        return self._instrument if instrument_id == self._instrument.instrument_id else None

    def submit(self, request):
        self.submit_calls += 1
        if self._submit_error is not None:
            raise self._submit_error
        return self._receipt_factory(request)

    def cancel(self, request):
        return self.submit(request)

    def reconcile(self, request):
        return self.submit(request)


class _FakePaperExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, snapshot):
        self.calls += 1
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=request.order.created_at,
            simulated=True,
            source="paper-venue",
            correlation_id=request.correlation_id,
        )


def _durable_gate(*, enabled: bool = True) -> DurableTradingGate:
    return DurableTradingGate(InMemoryTradingGateStateStore(), default_enabled=enabled)


def _approving_live_risk_evaluator():
    def approve(request) -> RiskResult:
        return RiskResult(RiskDecision.APPROVE, "approved for test")

    return approve


def _approving_india_evaluator():
    def approve(request) -> IndiaRuleResult:
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "approved",
            rule_set_version="test-b3",
            provenance="test-b3",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return approve


def _approving_india_session_evaluator():
    def allow(request) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "allowed",
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
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    return runtime


def _live_stack_kwargs(unit_of_work: _FakeUnitOfWork) -> dict:
    """The complete deterministic LIVE admission stack."""
    return {
        "application_runtime": _started_runtime(),
        "unit_of_work": unit_of_work,
        "trading_gate": _durable_gate(),
        "market_policy": india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        "submission_quarantine": _FakeSubmissionQuarantine(),
        "live_risk_evaluator": _approving_live_risk_evaluator(),
        "policy_verifier": policy_verifier(),
    }


def _live_orchestrator(unit_of_work: _FakeUnitOfWork, **overrides) -> ExecutionOrchestrator:
    kwargs = _live_stack_kwargs(unit_of_work)
    kwargs.update(overrides)
    return ExecutionOrchestrator(**kwargs)


def _assert_no_durable_work(
    unit_of_work: _FakeUnitOfWork, request: ApprovedExecutionRequest
) -> None:
    """Assert the attempt left no reservation, receipt, or quarantine evidence."""
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert not decision.reservation_pending, "no idempotency reservation may be created"
    assert decision.existing_receipt_id is None
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None


# ---------------------------------------------------------------------------
# The transactional path cannot be entered without valid admission
# ---------------------------------------------------------------------------


def test_transactional_path_without_authorization_is_rejected_before_durable_work() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)

    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, None)

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


@pytest.mark.parametrize(
    "forged",
    [
        True,
        "authorized",
        object(),
        {"client_order_id": "anything"},
    ],
    ids=["boolean", "string", "opaque-object", "mapping"],
)
def test_forged_authorization_values_are_rejected_before_durable_work(forged: object) -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)

    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, forged)

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_hand_built_authorization_with_a_guessed_proof_is_rejected() -> None:
    """A correctly shaped dataclass carries no authority on its own."""
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    forged = LiveSubmissionAuthorization(
        authorization_id=uuid4(),
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
        broker_identity=id(broker),
        unit_of_work_identity=id(unit_of_work),
        proof="0" * 64,
    )

    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, forged)

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_authorization_minted_by_another_orchestrator_instance_is_rejected() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    other_authority = LiveSubmissionAuthorizer()
    foreign = other_authority.issue(
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )

    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, foreign)

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_authorization_bound_to_another_request_is_rejected() -> None:
    admitted_request = _request()
    submitted_request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    authority = LiveSubmissionAuthorizer()
    wrong_request_authorization = authority.issue(
        client_order_id=admitted_request.order.client_order_id,
        request_fingerprint=request_fingerprint(admitted_request),
    )

    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            wrong_request_authorization,
            client_order_id=submitted_request.order.client_order_id,
            request_fingerprint=request_fingerprint(submitted_request),
        )
    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(
            submitted_request, broker, unit_of_work, wrong_request_authorization
        )

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, submitted_request)


def test_authorization_bound_to_another_execution_context_is_rejected() -> None:
    """The canonical fingerprint binds the execution context into the credential."""
    instrument = _instrument()
    foreign_context = ExecutionContext(
        account_id=_FOREIGN_ACCOUNT_ID,
        portfolio_id=PortfolioId("portfolio-qx267"),
        deployment_id=StrategyDeploymentId("deploy-qx267"),
        market=instrument.market,
        broker_connection_id=_CONNECTION_ID,
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=foreign_context,
        product=ProductCode("CNC"),
    )
    other_context_request = approved_request(
        order=build_order_from_intent(intent),
        execution_context=foreign_context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=ProductCode("CNC"),
    )
    submitted_request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    authority = LiveSubmissionAuthorizer()
    other_context_authorization = authority.issue(
        client_order_id=other_context_request.order.client_order_id,
        request_fingerprint=request_fingerprint(other_context_request),
    )

    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            other_context_authorization,
            client_order_id=submitted_request.order.client_order_id,
            request_fingerprint=request_fingerprint(submitted_request),
        )
    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(
            submitted_request, broker, unit_of_work, other_context_authorization
        )

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, submitted_request)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda a: replace(a, authorization_id=uuid4()),
        lambda a: replace(a, authorization_id=str(a.authorization_id)),
        lambda a: replace(a, client_order_id=uuid4()),
        lambda a: replace(a, broker_identity=101),
        lambda a: replace(a, unit_of_work_identity=202),
        lambda a: replace(a, request_fingerprint="0" * 64),
        lambda a: replace(a, proof="1" * 64),
        lambda a: replace(a, client_order_id="not-a-uuid"),
        lambda a: replace(a, request_fingerprint=None),
        lambda a: replace(a, proof=12345),
    ],
    ids=[
        "nonce",
        "stringified-nonce",
        "order-identity",
        "broker-identity",
        "unit-of-work-identity",
        "fingerprint",
        "proof",
        "string-order-id",
        "null-fingerprint",
        "int-proof",
    ],
)
def test_tampered_authorization_is_rejected(tamper) -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    authority = LiveSubmissionAuthorizer()
    issued = authority.issue(
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )
    tampered = tamper(issued)

    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            tampered,
            client_order_id=request.order.client_order_id,
            request_fingerprint=request_fingerprint(request),
        )
    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, tampered)

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_foreign_authorization_cannot_replay_or_submit_through_orchestrator() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    orchestrator = _live_orchestrator(unit_of_work)
    authority = LiveSubmissionAuthorizer()
    authorization = authority.issue(
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )

    # The credential is genuine for this standalone authority, but it is not
    # bound to the orchestrator's internal issuer and must never submit.
    with pytest.raises(LiveSubmissionAuthorizationError):
        orchestrator._execute_live_transactional(request, broker, unit_of_work, authorization)

    authority.authorize(
        authorization,
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )
    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            authorization,
            client_order_id=request.order.client_order_id,
            request_fingerprint=request_fingerprint(request),
        )

    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_transactional_path_requires_an_authorization_parameter() -> None:
    """No supported call shape can omit the admission credential."""
    parameters = inspect.signature(ExecutionOrchestrator._execute_live_transactional).parameters
    assert "authorization" in parameters
    assert parameters["authorization"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Public LIVE dispatch stays fail-closed without authoritative admission
# ---------------------------------------------------------------------------


def test_live_dispatch_blocks_when_the_risk_evaluator_is_absent() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work, live_risk_evaluator=None).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "risk evaluator" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_live_dispatch_blocks_when_the_quarantine_repository_is_absent() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work, submission_quarantine=None).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "quarantine" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_live_dispatch_blocks_when_the_gate_is_not_durable() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work, trading_gate=TradingGate(enabled=True)).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable TradingGate" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_live_dispatch_blocks_when_the_runtime_is_not_started() -> None:
    class NoopRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(
        unit_of_work,
        application_runtime=ApplicationRuntime(pending_recovery=NoopRecovery()),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "started ApplicationRuntime" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_live_dispatch_blocks_when_the_gate_is_disarmed() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work, trading_gate=_durable_gate(enabled=False)).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "trading is blocked" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_untrusted_rejecting_callback_is_not_invoked_as_live_authority() -> None:
    called = False

    def reject(request) -> RiskResult:
        nonlocal called
        called = True
        return RiskResult(RiskDecision.REJECT, "risk says no")

    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work, live_risk_evaluator=reject).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert called is False
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_live_dispatch_blocks_when_the_broker_account_does_not_match() -> None:
    foreign_broker = _FakeBroker(account_id=_FOREIGN_ACCOUNT_ID)
    foreign_request = _request()
    unit_of_work = _FakeUnitOfWork()

    blocked = _live_orchestrator(unit_of_work).execute(
        foreign_request, broker=foreign_broker
    )

    assert blocked.status is ExecutionDispatchStatus.BLOCKED
    assert "broker account does not match" in blocked.reason
    assert foreign_broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, foreign_request)


# ---------------------------------------------------------------------------
# The sanctioned path and non-LIVE behavior are unchanged
# ---------------------------------------------------------------------------


def test_arbitrary_risk_callback_cannot_authorize_live_submission() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    result = _live_orchestrator(unit_of_work).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_paper_execution_needs_no_live_authorization() -> None:
    request = _request(execution_mode=ExecutionMode.PAPER)
    instrument = _instrument()
    snapshot = Quote(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
        last=Decimal("100"),
    )
    paper_executor = _FakePaperExecutor()
    broker = _FakeBroker()

    result = ExecutionOrchestrator(
        paper_executor=paper_executor,
        trading_gate=_durable_gate(),
        policy_verifier=policy_verifier(),
    ).execute(request, snapshot=snapshot)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert paper_executor.calls == 1
    assert broker.submit_calls == 0


def test_public_dispatch_blocks_before_submit_when_authority_is_unavailable() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()

    first = _live_orchestrator(unit_of_work).execute(request, broker=broker)

    assert first.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in first.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)

    second = _live_orchestrator(unit_of_work).execute(request, broker=broker)

    assert second.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in second.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


def test_continue_partial_cannot_reach_live_broker_submission() -> None:
    request = _request()
    unit_of_work = _FakeUnitOfWork()
    broker = _FakeBroker()
    lifecycle = ExecutionLifecycle(
        client_order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    result = _live_orchestrator(unit_of_work).continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh"),
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "paper/replay" in result.reason
    assert broker.submit_calls == 0
    _assert_no_durable_work(unit_of_work, request)


# ---------------------------------------------------------------------------
# The authorizer object itself
# ---------------------------------------------------------------------------


def test_authorizer_accepts_its_own_fresh_authorization_exactly_once() -> None:
    authority = LiveSubmissionAuthorizer()
    authorization = authority.issue(
        client_order_id=uuid4(), request_fingerprint=request_fingerprint(_request())
    )

    authority.authorize(
        authorization,
        client_order_id=authorization.client_order_id,
        request_fingerprint=authorization.request_fingerprint,
    )
    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            authorization,
            client_order_id=authorization.client_order_id,
            request_fingerprint=authorization.request_fingerprint,
        )


def test_authorization_is_bound_to_broker_and_unit_of_work_identity() -> None:
    authority = LiveSubmissionAuthorizer()
    authorization = authority.issue(
        client_order_id=uuid4(),
        request_fingerprint="bound-request",
        broker_identity=101,
        unit_of_work_identity=202,
    )

    authority.authorize(
        authorization,
        client_order_id=authorization.client_order_id,
        request_fingerprint="bound-request",
        broker_identity=101,
        unit_of_work_identity=202,
    )

    fresh = authority.issue(
        client_order_id=authorization.client_order_id,
        request_fingerprint="bound-request",
        broker_identity=101,
        unit_of_work_identity=202,
    )
    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            fresh,
            client_order_id=fresh.client_order_id,
            request_fingerprint="bound-request",
            broker_identity=101,
            unit_of_work_identity=303,
        )


def test_orchestrator_does_not_expose_its_authorization_issuer() -> None:
    orchestrator = _live_orchestrator(_FakeUnitOfWork())

    assert not hasattr(orchestrator, "_live_submission_authority")


def test_stringified_consumed_authorization_id_cannot_bypass_replay_tracking() -> None:
    request = _request()
    authority = LiveSubmissionAuthorizer()
    authorization = authority.issue(
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )
    authority.authorize(
        authorization,
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
    )

    stringified = replace(authorization, authorization_id=str(authorization.authorization_id))
    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            stringified,
            client_order_id=request.order.client_order_id,
            request_fingerprint=request_fingerprint(request),
        )


def test_authorizer_rejects_a_foreign_authorization_with_the_same_binding() -> None:
    request = _request()
    client_order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)
    authority = LiveSubmissionAuthorizer()
    other_authority = LiveSubmissionAuthorizer()

    foreign = other_authority.issue(
        client_order_id=client_order_id, request_fingerprint=fingerprint
    )

    with pytest.raises(LiveSubmissionAuthorizationError):
        authority.authorize(
            foreign, client_order_id=client_order_id, request_fingerprint=fingerprint
        )


def test_authorizer_rejects_unsupported_values() -> None:
    authority = LiveSubmissionAuthorizer()
    client_order_id: UUID = uuid4()
    fingerprint = request_fingerprint(_request())

    for unsupported in (None, True, "authorized", object(), {"client_order_id": client_order_id}):
        with pytest.raises(LiveSubmissionAuthorizationError):
            authority.authorize(
                unsupported, client_order_id=client_order_id, request_fingerprint=fingerprint
            )
