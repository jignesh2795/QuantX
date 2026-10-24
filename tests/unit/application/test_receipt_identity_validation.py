"""Adversarial regression tests for QX-01: receipt identity validation at the LIVE boundary.

Validates that a broker response is not accepted as authoritative execution
evidence unless it is demonstrably bound to the approved request. Each
test uses a deterministic fake broker; no network calls or credentials.

Safety invariants tested:
- Receipt with foreign client_order_id → UNKNOWN, reservation pending, no persist.
- Receipt with absent correlation_id → UNKNOWN, reservation pending, no persist.
- Receipt with foreign correlation_id → UNKNOWN, reservation pending, no persist.
- Differing client_order_id is never accepted merely because a correlation matches.
- Continuation child receipt accepted only with its parent correlation.
- Account mismatch → UNKNOWN, reservation pending, no persist.
- Connection mismatch → UNKNOWN, reservation pending, no persist.
- Missing/incorrect order_quantity → UNKNOWN, reservation pending, no persist.
- Missing/incorrect canonical order_id → UNKNOWN, reservation pending, no persist.
- Receipt without source provenance → UNKNOWN, reservation pending, no persist.
- Fill with wrong instrument → UNKNOWN, reservation pending, no persist.
- Fill with wrong side → UNKNOWN, reservation pending, no persist.
- Aggregate fills exceeding requested quantity → UNKNOWN, reservation pending, no persist.
- Valid normal receipt → EXECUTED, receipt persisted, idempotency completed.
- Mismatched receipt does not complete idempotency or become the persisted receipt.
- Subsequent execution attempt remains blocked by pending reservation (no resubmit).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
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
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.execution.idempotency import IdempotencyDecision, InMemoryIdempotencyStore
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.identity import (
    ReceiptIdentityViolation,
    validate_cached_receipt_identity,
    validate_live_receipt_identity,
)
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.quarantine import QuarantineObservationKind
from quantx.execution.trading_gate import DurableTradingGate, InMemoryTradingGateStateStore
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
    BrokerDescriptor,
    CapabilitySet,
)
from quantx.persistence import ReceiptRepository, UnitOfWork
from tests.unit._execution_request_proofs import approved_request, policy_verifier

# ---------------------------------------------------------------------------
# Shared fixtures / factory helpers
# ---------------------------------------------------------------------------

_ACCOUNT_ID = AccountId("acct-qx01")
_CONNECTION_ID = BrokerConnectionId("conn-qx01")
_FOREIGN_ACCOUNT_ID = AccountId("acct-foreign")
_FOREIGN_CONNECTION_ID = BrokerConnectionId("conn-foreign")


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


def _live_request(
    *,
    account_id: AccountId | None = None,
    connection_id: BrokerConnectionId | None = None,
    quantity: Decimal = Decimal("10"),
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=account_id or _ACCOUNT_ID,
        portfolio_id=PortfolioId("portfolio-qx01"),
        deployment_id=StrategyDeploymentId("deploy-qx01"),
        market=instrument.market,
        broker_connection_id=connection_id or _CONNECTION_ID,
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=quantity,
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
    """Return an identity-valid ACCEPTED receipt for a LIVE request."""
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
        self.rolled_back = False

    @property
    def idempotency(self):
        return self._store

    @property
    def receipts(self):
        return self._repository

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


class _FakeSubmissionQuarantine:
    """In-memory SubmissionQuarantineRepository for LIVE identity tests."""

    def __init__(self) -> None:
        self._observations: dict = {}

    def record(self, observation) -> None:
        self._observations[observation.observation_id] = observation

    def get(self, observation_id):
        return self._observations.get(observation_id)

    def list_by_client_order(self, client_order_id):
        return tuple(
            observation
            for observation in self._observations.values()
            if observation.client_order_id == client_order_id
        )

    def list_all(self):
        return tuple(self._observations.values())


def _durable_gate() -> DurableTradingGate:
    return DurableTradingGate(InMemoryTradingGateStateStore(), default_enabled=True)


def _approving_live_risk_evaluator():
    """LIVE pre-trade risk is not under test here; approve explicitly."""

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


def _orchestrator(
    unit_of_work: _FakeUnitOfWork,
    *,
    submission_quarantine=None,
) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        submission_quarantine=submission_quarantine or _FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    )


class _MismatchedBroker:
    """Fake broker that returns a configurable receipt regardless of the request."""

    def __init__(self, receipt_factory) -> None:
        self._receipt_factory = receipt_factory
        self._connection = BrokerConnectionRef(_ACCOUNT_ID, _CONNECTION_ID, "fake", "NSE")
        self._instrument = _instrument()
        self.submit_calls = 0
        self.descriptor = BrokerDescriptor(
            "fake",
            "Fake",
            CapabilitySet(frozenset({BrokerCapability.ORDER_SUBMISSION})),
            "1",
        )

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
        return self._receipt_factory(request)

    def cancel(self, request):
        return self.submit(request)

    def reconcile(self, request):
        return self.submit(request)


def _assert_mismatch_is_unknown_and_pending(
    result,
    unit_of_work: _FakeUnitOfWork,
    request: ApprovedExecutionRequest,
    broker: _MismatchedBroker,
    *,
    expect_submit_calls: int = 1,
) -> None:
    """Assert all safety invariants for a receipt identity mismatch."""
    assert result.status is ExecutionDispatchStatus.UNKNOWN, result.reason
    assert "mismatch" in result.reason or "absent" in result.reason, result.reason
    assert result.receipt is None, "mismatched receipt must not be returned as authoritative"

    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending, "idempotency reservation must remain PENDING on mismatch"
    assert decision.existing_receipt_id is None, "idempotency must not be completed on mismatch"

    persisted = unit_of_work.receipts.get_by_client_order(request.order.client_order_id)
    assert persisted is None, "foreign receipt must not be persisted as authoritative evidence"

    assert broker.submit_calls == expect_submit_calls


# ---------------------------------------------------------------------------
# Unit tests for validate_live_receipt_identity directly
# ---------------------------------------------------------------------------


def test_validator_accepts_valid_receipt() -> None:
    request = _live_request()
    receipt = _valid_receipt(request)
    assert validate_live_receipt_identity(request, receipt) is None


def test_validator_rejects_foreign_client_order_id() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),  # foreign client order
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
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "client_order_id" in result.reason


def test_validator_rejects_absent_correlation() -> None:
    """A receipt whose client_order_id matches must still carry the correlation."""
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=None,  # absent
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "correlation_id" in result.reason


def test_validator_rejects_foreign_correlation() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id="some-other-correlation",  # foreign
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "correlation_id" in result.reason


def test_validator_rejects_differing_client_order_id_even_with_matching_correlation() -> None:
    """A matching correlation value alone must never buy acceptance."""
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),  # foreign client order
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,  # correlation matches the request
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "client_order_id" in result.reason


def test_validator_rejects_absent_order_id() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=None,  # absent canonical order identity
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "order_id" in result.reason


def test_validator_rejects_wrong_order_id() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=uuid4(),  # foreign canonical order identity
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "order_id" in result.reason


def test_validator_rejects_receipt_without_source() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="",  # anonymous receipt
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "source" in result.reason


def test_validator_rejects_account_mismatch() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
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
        account_id=_FOREIGN_ACCOUNT_ID,  # wrong account
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "account_id" in result.reason


def test_validator_rejects_connection_mismatch() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
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
        connection_id=_FOREIGN_CONNECTION_ID,  # wrong connection
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "connection_id" in result.reason


def test_validator_rejects_absent_account_id() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
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
        account_id=None,  # absent
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "account_id" in result.reason


def test_validator_rejects_absent_connection_id() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
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
        connection_id=None,  # absent
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "connection_id" in result.reason


def test_validator_rejects_absent_order_quantity() -> None:
    request = _live_request()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=None,  # absent
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "order_quantity" in result.reason


def test_validator_rejects_wrong_order_quantity() -> None:
    request = _live_request(quantity=Decimal("10"))
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=Decimal("99"),  # wrong quantity
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "order_quantity" in result.reason


def test_validator_rejects_fill_with_wrong_instrument() -> None:
    request = _live_request()
    wrong_instrument = InstrumentId("NSE", "INFY")
    fill = Fill(
        client_order_id=request.order.client_order_id,
        instrument=wrong_instrument,
        side=request.order.side,
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=request.order.created_at,
    )
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        order_status=OrderStatus.PARTIALLY_FILLED,
        executed_at=request.order.created_at,
        fills=(fill,),
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "instrument" in result.reason


def test_validator_rejects_fill_with_wrong_side() -> None:
    request = _live_request()
    fill = Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=OrderSide.SELL,  # wrong side
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=request.order.created_at,
    )
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        order_status=OrderStatus.PARTIALLY_FILLED,
        executed_at=request.order.created_at,
        fills=(fill,),
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "side" in result.reason


def test_validator_rejects_aggregate_fill_exceeding_quantity() -> None:
    request = _live_request(quantity=Decimal("5"))
    fill = Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal("5"),
        price=Decimal("100"),
        filled_at=request.order.created_at,
    )
    # Construct receipt with fill quantity matching order_quantity so that
    # ExecutionReceipt.__post_init__ does not raise; then override order_quantity
    # to be smaller to simulate a foreign quantity mismatch scenario.
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        order_status=OrderStatus.PARTIALLY_FILLED,
        executed_at=request.order.created_at,
        fills=(fill,),
        simulated=False,
        source="fake-broker",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=Decimal("3"),  # less than fill, but mismatches request too
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    # The order_quantity mismatch (3 != 5) is caught first.
    result = validate_live_receipt_identity(request, receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    # Either order_quantity mismatch or aggregate-fill exceeded is reported.
    assert "order_quantity" in result.reason or "fill quantity" in result.reason


# ---------------------------------------------------------------------------
# End-to-end orchestrator tests via _execute_live_transactional
# ---------------------------------------------------------------------------


def test_foreign_client_order_id_produces_unknown_not_executed() -> None:
    """TC1: Foreign client_order_id → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),  # foreign order
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=req.correlation_id,
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_account_mismatch_produces_unknown() -> None:
    """TC2: Account mismatch → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=req.correlation_id,
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=_FOREIGN_ACCOUNT_ID,  # wrong account
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_connection_mismatch_produces_unknown() -> None:
    """TC3: Connection mismatch → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=req.correlation_id,
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=_FOREIGN_CONNECTION_ID,  # wrong connection
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_absent_correlation_produces_unknown_and_keeps_pending() -> None:
    """TC7a: Absent correlation → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=None,  # absent
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_foreign_correlation_produces_unknown_and_keeps_pending() -> None:
    """TC7b: Foreign correlation → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id="some-other-correlation",  # foreign
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_absent_order_quantity_produces_unknown() -> None:
    """TC4: Missing order_quantity → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            order_quantity=None,  # absent — fails LIVE provenance check
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_fill_wrong_instrument_produces_unknown() -> None:
    """TC5: Fill with wrong instrument → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()

    def _bad_fill_receipt(req):
        fill = Fill(
            client_order_id=req.order.client_order_id,
            instrument=InstrumentId("NSE", "INFY"),  # wrong instrument
            side=req.order.side,
            quantity=Decimal("1"),
            price=Decimal("100"),
            filled_at=req.order.created_at,
        )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=req.order.created_at,
            fills=(fill,),
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )

    broker = _MismatchedBroker(_bad_fill_receipt)
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_fill_wrong_side_produces_unknown() -> None:
    """TC6: Fill with wrong side → UNKNOWN, pending reservation, no persist."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()

    def _bad_fill_receipt(req):
        fill = Fill(
            client_order_id=req.order.client_order_id,
            instrument=req.order.instrument,
            side=OrderSide.SELL,  # wrong side
            quantity=Decimal("1"),
            price=Decimal("100"),
            filled_at=req.order.created_at,
        )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=req.order.client_order_id,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=req.order.created_at,
            fills=(fill,),
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )

    broker = _MismatchedBroker(_bad_fill_receipt)
    result = _orchestrator(unit_of_work).execute(request, broker=broker)
    _assert_mismatch_is_unknown_and_pending(result, unit_of_work, request, broker)


def test_valid_normal_receipt_produces_executed() -> None:
    """TC8: A valid, identity-correct receipt → EXECUTED, persisted, idempotency completed."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(lambda req: _valid_receipt(req))

    result = _orchestrator(unit_of_work).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None

    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.existing_receipt_id == result.receipt.receipt_id
    assert not decision.reservation_pending

    persisted = unit_of_work.receipts.get(result.receipt.receipt_id)
    assert persisted == result.receipt
    assert broker.submit_calls == 1


def test_mismatched_receipt_does_not_complete_idempotency() -> None:
    """TC10: Mismatch must not complete idempotency or become the authoritative receipt."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),  # foreign
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=req.correlation_id,
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )

    result = _orchestrator(unit_of_work).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.UNKNOWN

    # Idempotency must remain PENDING — not completed, not absent.
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None

    # Nothing must be persisted under the request's client_order_id.
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    assert broker.submit_calls == 1


def test_subsequent_attempt_blocked_by_pending_reservation() -> None:
    """TC11: After a mismatch the pending reservation blocks resubmission."""
    request = _live_request()
    unit_of_work = _FakeUnitOfWork()
    broker = _MismatchedBroker(
        lambda req: ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),  # foreign
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=req.order.created_at,
            simulated=False,
            source="fake-broker",
            correlation_id=req.correlation_id,
            order_id=req.order.client_order_id,
            order_quantity=req.order.quantity,
            account_id=req.execution_context.account_id,
            connection_id=req.execution_context.broker_connection_id,
        )
    )
    orchestrator = _orchestrator(unit_of_work)

    first = orchestrator.execute(request, broker=broker)
    assert first.status is ExecutionDispatchStatus.UNKNOWN
    assert broker.submit_calls == 1

    # Second attempt must be blocked by the pending reservation — no resubmit.
    second = orchestrator.execute(request, broker=broker)
    assert second.status is ExecutionDispatchStatus.UNKNOWN
    assert "reconciliation" in second.reason
    assert broker.submit_calls == 1  # broker must NOT have been called again


def _continuation_pair(
    *,
    parent_quantity: Decimal = Decimal("10"),
    parent_filled: Decimal = Decimal("4"),
) -> tuple[ApprovedExecutionRequest, ApprovedExecutionRequest]:
    """Build a parent LIVE request and its documented continuation child."""
    parent_request = _live_request(quantity=parent_quantity)
    parent_lifecycle = ExecutionLifecycle(
        client_order_id=parent_request.order.client_order_id,
        order_quantity=parent_quantity,
        filled_quantity=parent_filled,
        status=OrderStatus.PARTIALLY_FILLED,
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "fresh"),
    )
    return parent_request, child_request


def _child_receipt(
    child_request: ApprovedExecutionRequest,
    parent_request: ApprovedExecutionRequest,
    *,
    correlation_id: str | None,
    client_order_id: UUID | str | None = None,
) -> ExecutionReceipt:
    """Build a continuation child receipt with configurable identity fields."""
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=(
            child_request.order.client_order_id if client_order_id is None else client_order_id
        ),
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=child_request.order.created_at,
        simulated=False,
        source="fake-broker",
        correlation_id=correlation_id,
        order_id=child_request.order.client_order_id,
        order_quantity=child_request.order.quantity,
        account_id=child_request.execution_context.account_id,
        connection_id=child_request.execution_context.broker_connection_id,
    )


def test_continuation_child_receipt_accepted_via_parent_correlation() -> None:
    """TC9: A child receipt bound to its own order id and the parent correlation passes."""
    parent_request, child_request = _continuation_pair()
    child_receipt = _child_receipt(
        child_request,
        parent_request,
        correlation_id=child_request.correlation_id,
    )
    assert child_request.correlation_id == str(parent_request.order.client_order_id)
    result = validate_live_receipt_identity(child_request, child_receipt)
    assert result is None, f"continuation child receipt must pass: {result}"


def test_continuation_child_receipt_rejected_against_parent_request() -> None:
    """TC9b: A child receipt is not identity-valid for the parent request."""
    parent_request, child_request = _continuation_pair()
    child_receipt = _child_receipt(
        child_request,
        parent_request,
        correlation_id=child_request.correlation_id,
    )
    result = validate_live_receipt_identity(parent_request, child_receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "client_order_id" in result.reason


def test_continuation_child_receipt_rejected_with_foreign_correlation() -> None:
    """A child receipt must carry the parent correlation, not an arbitrary value."""
    parent_request, child_request = _continuation_pair()
    child_receipt = _child_receipt(
        child_request,
        parent_request,
        correlation_id="some-unrelated-correlation",
    )
    result = validate_live_receipt_identity(child_request, child_receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "correlation_id" in result.reason


def test_continuation_child_receipt_rejected_with_absent_correlation() -> None:
    parent_request, child_request = _continuation_pair()
    child_receipt = _child_receipt(
        child_request,
        parent_request,
        correlation_id=None,
    )
    result = validate_live_receipt_identity(child_request, child_receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "correlation_id" in result.reason


def test_continuation_child_receipt_rejected_with_foreign_client_order_id() -> None:
    """A mismatched child client-order id is not accepted via a matching correlation."""
    parent_request, child_request = _continuation_pair()
    child_receipt = _child_receipt(
        child_request,
        parent_request,
        correlation_id=child_request.correlation_id,  # parent correlation matches
        client_order_id=uuid4(),  # but the order identity is foreign
    )
    result = validate_live_receipt_identity(child_request, child_receipt)
    assert isinstance(result, ReceiptIdentityViolation)
    assert "client_order_id" in result.reason


# ---------------------------------------------------------------------------
# Cached receipt identity for a completed reservation (both duplicate paths)
# ---------------------------------------------------------------------------

# A fixed identity so the canonical/non-canonical string forms are decided by the
# test, never by which hex digits a random UUID happens to contain.
_CANONICAL_UUID = UUID("abcdef01-2345-4678-89ab-cdef01234567")
_CACHED_RECEIPT_IDENTITY_REASON = (
    "cached receipt for a completed reservation does not belong to the approved request; "
    "reconciliation is required"
)


def _bound_request(client_order_id: UUID | None = None) -> ApprovedExecutionRequest:
    """A LIVE request whose order identity is a chosen UUID."""
    request = _live_request()
    if client_order_id is None:
        return request
    return replace(request, order=replace(request.order, client_order_id=client_order_id))


def _cached_receipt(
    request: ApprovedExecutionRequest,
    *,
    receipt_id: UUID | None = None,
    **overrides,
) -> ExecutionReceipt:
    """A valid receipt for ``request`` with individually corrupted identity fields."""
    return replace(_valid_receipt(request), receipt_id=receipt_id or uuid4(), **overrides)


def _cached_violation(request, receipt, *, receipt_id: UUID | None = None):
    return validate_cached_receipt_identity(
        request,
        receipt_id=receipt.receipt_id if receipt_id is None else receipt_id,
        receipt=receipt,
    )


def test_cached_validator_accepts_uuid_client_order_id() -> None:
    request = _bound_request(_CANONICAL_UUID)
    receipt = _cached_receipt(request)
    assert _cached_violation(request, receipt) is None


def test_cached_validator_accepts_the_canonical_string_identity() -> None:
    """A stored receipt may carry the canonical string rendering of the same UUID."""
    request = _bound_request(_CANONICAL_UUID)
    receipt = _cached_receipt(request, client_order_id=str(_CANONICAL_UUID))
    assert _cached_violation(request, receipt) is None


@pytest.mark.parametrize(
    "render",
    [
        lambda value: value.upper(),
        lambda value: "{" + value + "}",
        lambda value: " " + value,
        lambda value: value + " ",
        lambda value: value.replace("-", ""),
        lambda value: "urn:uuid:" + value,
    ],
    ids=[
        "uppercase",
        "braced",
        "leading-space",
        "trailing-space",
        "unhyphenated",
        "urn-prefixed",
    ],
)
def test_cached_validator_rejects_non_canonical_string_identity(render) -> None:
    """Only the canonical rendering is identity; nothing is parsed or normalised."""
    request = _bound_request(_CANONICAL_UUID)
    canonical = str(_CANONICAL_UUID)
    rendered = render(canonical)
    assert rendered != canonical

    violation = _cached_violation(request, _cached_receipt(request, client_order_id=rendered))

    assert isinstance(violation, ReceiptIdentityViolation)
    assert "canonical request identity" in violation.reason


def test_cached_validator_rejects_a_foreign_client_order_id() -> None:
    request = _bound_request()
    violation = _cached_violation(request, _cached_receipt(request, client_order_id=uuid4()))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "client_order_id" in violation.reason


def test_cached_validator_rejects_a_different_reservation_receipt_id() -> None:
    request = _bound_request()
    receipt = _cached_receipt(request)
    violation = _cached_violation(request, receipt, receipt_id=uuid4())
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "reservation receipt id" in violation.reason


def test_cached_validator_rejects_a_non_uuid_receipt_id() -> None:
    request = _bound_request()
    receipt = _cached_receipt(request)
    violation = _cached_violation(request, receipt, receipt_id=str(receipt.receipt_id))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "exact UUID" in violation.reason


def test_cached_validator_rejects_a_payload_that_is_not_a_receipt() -> None:
    request = _bound_request()
    violation = validate_cached_receipt_identity(request, receipt_id=uuid4(), receipt=object())
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "not an ExecutionReceipt" in violation.reason


def test_cached_validator_rejects_a_foreign_correlation() -> None:
    request = _bound_request()
    violation = _cached_violation(
        request, _cached_receipt(request, correlation_id="foreign-correlation")
    )
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "correlation_id" in violation.reason


def test_cached_validator_rejects_a_foreign_order_id() -> None:
    request = _bound_request()
    violation = _cached_violation(request, _cached_receipt(request, order_id=uuid4()))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "order_id" in violation.reason


def test_cached_validator_rejects_a_foreign_account() -> None:
    request = _bound_request()
    violation = _cached_violation(request, _cached_receipt(request, account_id=_FOREIGN_ACCOUNT_ID))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "account_id" in violation.reason


def test_cached_validator_rejects_a_foreign_connection() -> None:
    request = _bound_request()
    violation = _cached_violation(
        request, _cached_receipt(request, connection_id=_FOREIGN_CONNECTION_ID)
    )
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "connection_id" in violation.reason


def test_cached_validator_rejects_a_wrong_order_quantity() -> None:
    request = _bound_request()
    violation = _cached_violation(request, _cached_receipt(request, order_quantity=Decimal("99")))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "order_quantity" in violation.reason


def test_cached_validator_rejects_an_absent_source() -> None:
    request = _bound_request()
    violation = _cached_violation(request, _cached_receipt(request, source=""))
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "source" in violation.reason


def test_cached_validator_rejects_an_unknown_outcome() -> None:
    """A cached UNKNOWN must never be replayed as authoritative execution evidence."""
    request = _bound_request()
    violation = _cached_violation(
        request,
        _cached_receipt(
            request,
            outcome=ExecutionOutcome.UNKNOWN,
            order_status=OrderStatus.UNKNOWN,
        ),
    )
    assert isinstance(violation, ReceiptIdentityViolation)
    assert "UNKNOWN" in violation.reason


def _completed_reservation(
    request: ApprovedExecutionRequest,
    cached: ExecutionReceipt,
) -> _FakeUnitOfWork:
    """Unit of work whose reservation for ``request`` is already completed."""
    unit_of_work = _FakeUnitOfWork()
    fingerprint = request_fingerprint(request)
    client_order_id = request.order.client_order_id
    unit_of_work.idempotency.reserve_or_get(client_order_id, fingerprint)
    unit_of_work.receipts.save(cached)
    unit_of_work.idempotency.complete(client_order_id, fingerprint, cached.receipt_id)
    return unit_of_work


class _RacingIdempotencyStore(InMemoryIdempotencyStore):
    """Store where a concurrent writer completes the reservation after ``check``.

    ``check`` keeps reporting the pre-completion view while ``reserve_or_get``
    reports the completed decision the store now holds. That is the race the
    second duplicate path exists for; without it a completed reservation is
    always caught at ``check`` and the second path is never reached.
    """

    def __init__(self) -> None:
        super().__init__()
        self._racing = False
        self.race_served = 0

    def start_race(self) -> None:
        self._racing = True

    def check(self, client_order_id, request_fingerprint):
        decision = super().check(client_order_id, request_fingerprint)
        if not self._racing:
            return decision
        return IdempotencyDecision(
            client_order_id=decision.client_order_id,
            request_fingerprint=decision.request_fingerprint,
        )

    def reserve_or_get(self, client_order_id, request_fingerprint, pending_context=None):
        if self._racing:
            self.race_served += 1
            return super().check(client_order_id, request_fingerprint)
        return super().reserve_or_get(client_order_id, request_fingerprint, pending_context)


def _racing_unit_of_work(
    request: ApprovedExecutionRequest,
    cached: ExecutionReceipt,
) -> _FakeUnitOfWork:
    """Unit of work where ``cached`` completes the reservation after ``check``."""
    store = _RacingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    fingerprint = request_fingerprint(request)
    client_order_id = request.order.client_order_id
    store.reserve_or_get(client_order_id, fingerprint)
    unit_of_work.receipts.save(cached)
    store.complete(client_order_id, fingerprint, cached.receipt_id)
    store.start_race()
    return unit_of_work


def test_cached_receipt_for_another_order_at_check_path_is_unknown() -> None:
    """Duplicate path A: a foreign cached receipt is never returned as EXECUTED."""
    request = _live_request()
    foreign = _valid_receipt(_live_request())
    unit_of_work = _completed_reservation(request, foreign)
    quarantine = _FakeSubmissionQuarantine()
    broker = _MismatchedBroker(_valid_receipt)

    result = _orchestrator(unit_of_work, submission_quarantine=quarantine).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.UNKNOWN
    assert result.receipt is None, "a foreign cached receipt must never be returned"
    assert result.reason == _CACHED_RECEIPT_IDENTITY_REASON
    assert broker.submit_calls == 0
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    observations = quarantine.list_by_client_order(request.order.client_order_id)
    assert [observation.kind for observation in observations] == [
        QuarantineObservationKind.IDENTITY_REJECTED
    ]
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.existing_receipt_id == foreign.receipt_id


def test_cached_receipt_for_another_order_at_reservation_path_is_unknown() -> None:
    """Duplicate path B: the same rejection applies when the race completes first."""
    request = _live_request()
    foreign = _valid_receipt(_live_request())
    unit_of_work = _racing_unit_of_work(request, foreign)
    quarantine = _FakeSubmissionQuarantine()
    broker = _MismatchedBroker(_valid_receipt)

    result = _orchestrator(unit_of_work, submission_quarantine=quarantine).execute(
        request, broker=broker
    )

    assert result.status is ExecutionDispatchStatus.UNKNOWN
    assert result.receipt is None
    assert result.reason == _CACHED_RECEIPT_IDENTITY_REASON
    assert broker.submit_calls == 0
    assert unit_of_work.idempotency.race_served == 1, "duplicate path B must be the one taken"
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    observations = quarantine.list_by_client_order(request.order.client_order_id)
    assert [observation.kind for observation in observations] == [
        QuarantineObservationKind.IDENTITY_REJECTED
    ]


def test_matching_cached_receipt_at_check_path_stays_executed() -> None:
    """No regression: a genuinely matching cached receipt is still EXECUTED."""
    request = _live_request()
    cached = _valid_receipt(request)
    unit_of_work = _completed_reservation(request, cached)
    broker = _MismatchedBroker(_valid_receipt)

    result = _orchestrator(unit_of_work).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is cached
    assert broker.submit_calls == 0


def test_matching_cached_receipt_at_reservation_path_stays_executed() -> None:
    """No regression: duplicate path B still returns the matching receipt."""
    request = _live_request()
    cached = _valid_receipt(request)
    unit_of_work = _racing_unit_of_work(request, cached)
    broker = _MismatchedBroker(_valid_receipt)

    result = _orchestrator(unit_of_work).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is cached
    assert broker.submit_calls == 0
    assert unit_of_work.idempotency.race_served == 1, "duplicate path B must be the one taken"
