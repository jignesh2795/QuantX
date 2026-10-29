from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread
from typing import cast
from uuid import UUID, uuid4

import pytest

from quantx.application.evidence_refresh import EvidenceRefreshOutcome
import quantx.application.execution as execution_module
from quantx.application.execution import (
    ExecutionDispatchStatus,
    ExecutionOrchestrator,
    ExecutionResult,
)
from quantx.application.pending_recovery import PendingRecoveryResult, PendingRecoveryRun
from quantx.application.reconciliation import (
    OrderStateReconciliationResult,
    OrderWorkflowStatus,
)
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType, PositionEffect
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
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.execution.idempotency import (
    IdempotencyDecision,
    IdempotencyDecisionValidationError,
    InMemoryIdempotencyStore,
    NotSubmittedSource,
)
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import BrokerPort, ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.quarantine import QuarantineObservationKind
from quantx.execution.session_guard import SessionExecutionGuard, SessionGuardResult
from quantx.execution.submission_preflight import BrokerPreflightRejected
from quantx.execution.trading_gate import (
    DurableTradingGate,
    InMemoryTradingGateStateStore,
    TradingGate,
)
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.market_checks import india_market_policy
from quantx.india.market_pack import INDIA_EQUITY_PRODUCT_SELECTION
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
from quantx.integrations.reconciliation.account import (
    ReconciliationFinding,
    ReconciliationReport,
)
from quantx.integrations.reconciliation.account import (
    ReconciliationStatus as AccountReconciliationStatus,
)
from quantx.integrations.reconciliation.orders import (
    OrderObservation,
    OrderReconciliationResult,
    OrderReconciliationStatus,
)
from quantx.integrations.reconciliation.positions import PositionReconciliation
from quantx.integrations.reconciliation.positions import (
    ReconciliationStatus as PositionReconciliationStatus,
)
from quantx.persistence import ReceiptRepository, UnitOfWork
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteIdempotencyStore,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.ports.market_checks import MarketPolicyConfig
from tests.unit._execution_request_proofs import approved_request, policy_verifier


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


def _request(
    mode: ExecutionMode,
    *,
    account_id: AccountId | None = None,
    connection_id: BrokerConnectionId | None = None,
    required_capabilities: frozenset[str] = frozenset(),
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    live = mode is ExecutionMode.LIVE
    context = ExecutionContext(
        account_id=account_id or AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=connection_id,
        execution_mode=mode,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    product = ProductCode("CNC") if live else None
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
        required_capabilities=required_capabilities,
        product=product,
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=product,
    )


class FakePaperExecutor:
    def execute(self, request: ApprovedExecutionRequest, *, snapshot: Quote) -> ExecutionReceipt:
        fill = Fill(
            client_order_id=request.order.client_order_id,
            instrument=request.order.instrument,
            side=request.order.side,
            quantity=request.order.quantity,
            price=Decimal("100"),
            filled_at=snapshot.timestamp,
        )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=snapshot.timestamp,
            fills=(fill,),
            simulated=True,
            source="fake-paper",
        )


class FakeBroker:
    def __init__(
        self,
        *,
        account_id: AccountId | None = None,
        connection_id: BrokerConnectionId | None = None,
        healthy: bool = True,
        capabilities: frozenset[BrokerCapability] | None = None,
        instrument: Instrument | None = None,
    ):
        account_id = account_id or AccountId("acct-1")
        connection_id = connection_id or BrokerConnectionId("conn-1")
        capabilities = capabilities or frozenset({BrokerCapability.ORDER_SUBMISSION})
        self._instrument = instrument or _instrument()
        self._connection = BrokerConnectionRef(account_id, connection_id, "fake", "NSE")
        self._healthy = healthy
        self._capabilities = CapabilitySet(capabilities)
        self.submit_calls = 0
        self.descriptor = BrokerDescriptor("fake", "Fake", self._capabilities, "1")

    @property
    def connection(self):
        return self._connection

    def health(self):
        return self._healthy

    def capabilities(self):
        return self._capabilities

    def instrument(self, instrument_id):
        return self._instrument if instrument_id == self._instrument.instrument_id else None

    def submit(self, request):
        self.submit_calls += 1
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
            account_id=self.connection.account_id,
            connection_id=self.connection.connection_id,
        )

    def cancel(self, request):
        return self.submit(request)

    def reconcile(self, request):
        return self.submit(request)


class _FakeReceiptRepository(ReceiptRepository):
    def __init__(self) -> None:
        self._receipts = {}

    def save(self, receipt) -> None:
        self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id):
        return self._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id):
        for receipt in self._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None


class _FakeSubmissionQuarantine:
    """In-memory SubmissionQuarantineRepository for non-SQLite LIVE tests."""

    def __init__(self) -> None:
        self._observations = {}

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


def _durable_gate() -> DurableTradingGate:
    return DurableTradingGate(InMemoryTradingGateStateStore(), default_enabled=True)


def _approving_live_risk_evaluator():
    """LIVE pre-trade risk is not under test here; approve explicitly."""

    def approve(request) -> RiskResult:
        return RiskResult(RiskDecision.APPROVE, "approved for test")

    return approve


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
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    return runtime


def _live_request():
    return _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )


def _execute_admitted_transaction(
    orchestrator: ExecutionOrchestrator,
    request: ApprovedExecutionRequest,
    broker: BrokerPort,
    unit_of_work: UnitOfWork,
) -> ExecutionResult:
    """Exercise transaction semantics after an explicitly simulated admission.

    Public LIVE dispatch is separately required to reject untrusted evidence.
    These unit tests isolate the downstream transaction contract using a
    single-use credential bound to the exact fake broker and unit of work.
    """
    with execution_module._LIVE_SUBMISSION_AUTHORITIES_LOCK:
        authority = execution_module._LIVE_SUBMISSION_AUTHORITIES.get(orchestrator)
    assert authority is not None
    authorization = authority.issue(
        client_order_id=request.order.client_order_id,
        request_fingerprint=request_fingerprint(request),
        broker_identity=id(broker),
        unit_of_work_identity=id(unit_of_work),
    )
    return orchestrator._execute_live_transactional(request, broker, unit_of_work, authorization)


def test_paper_requires_an_observed_snapshot() -> None:
    orchestrator = ExecutionOrchestrator(
        paper_executor=FakePaperExecutor(),
        policy_verifier=policy_verifier(),
    )
    result = orchestrator.execute(_request(ExecutionMode.PAPER))
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "snapshot" in result.reason


def test_orchestrator_carries_no_idempotency_store() -> None:
    """The orchestrator owns no idempotency state of its own.

    Paper/replay paths use their venue idempotency stores and LIVE uses
    the durable ``UnitOfWork.idempotency`` transaction, so the dispatcher
    constructs and dispatches identically without the removed store.
    """
    orchestrator = ExecutionOrchestrator(
        paper_executor=FakePaperExecutor(),
        policy_verifier=policy_verifier(),
    )
    assert not hasattr(orchestrator, "_idempotency")

    request = _request(ExecutionMode.PAPER)
    snapshot = Quote(
        instrument=request.order.instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )
    result = orchestrator.execute(request, snapshot=snapshot)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None


def test_orchestrator_rejects_idempotency_argument() -> None:
    """The removed ``idempotency`` constructor argument stays removed."""
    with pytest.raises(TypeError):
        ExecutionOrchestrator(
            paper_executor=FakePaperExecutor(),
            idempotency=InMemoryIdempotencyStore(),  # type: ignore[call-arg]
            policy_verifier=policy_verifier(),
        )


def test_paper_rejects_snapshot_for_wrong_instrument() -> None:
    orchestrator = ExecutionOrchestrator(
        paper_executor=FakePaperExecutor(),
        policy_verifier=policy_verifier(),
    )
    wrong = Quote(
        instrument=InstrumentId("NSE", "INFY"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )
    result = orchestrator.execute(_request(ExecutionMode.PAPER), snapshot=wrong)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "instrument" in result.reason


def test_paper_executes_with_matching_snapshot() -> None:
    orchestrator = ExecutionOrchestrator(
        paper_executor=FakePaperExecutor(),
        policy_verifier=policy_verifier(),
    )
    request = _request(ExecutionMode.PAPER)
    snapshot = Quote(
        instrument=request.order.instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )

    result = orchestrator.execute(request, snapshot=snapshot)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.outcome is ExecutionOutcome.FILLED
    assert result.receipt.fills
    assert result.receipt.fills[0].quantity == request.order.quantity


def test_live_requires_a_broker() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
        required_capabilities=frozenset({BrokerCapability.ORDER_SUBMISSION}),
    )
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "broker adapter" in result.reason


def test_live_blocks_account_mismatch() -> None:
    request = _request(
        ExecutionMode.LIVE,
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker(account_id=AccountId("acct-2"))
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "account" in result.reason


def test_live_blocks_connection_mismatch() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker(connection_id=BrokerConnectionId("conn-2"))
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "connection" in result.reason


def test_live_blocks_unhealthy_broker() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(
        request,
        broker=FakeBroker(healthy=False),
    )
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "healthy" in result.reason


def test_live_blocks_missing_required_capability() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
        required_capabilities=frozenset(
            {
                BrokerCapability.ORDER_SUBMISSION,
                BrokerCapability.ORDER_CANCELLATION,
            }
        ),
    )
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=FakeBroker())
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "capabilities" in result.reason


def test_live_blocks_broker_instrument_market_mismatch() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    wrong_market_instrument = replace(
        _instrument(),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"),
    )
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(
        request,
        broker=FakeBroker(instrument=wrong_market_instrument),
    )
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "market" in result.reason


def test_live_submits_only_after_identity_health_and_capability_checks() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
        required_capabilities=frozenset({BrokerCapability.ORDER_SUBMISSION}),
    )
    broker = FakeBroker()
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert broker.submit_calls == 0


def test_live_submission_is_idempotent_through_canonical_boundary() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    unit_of_work = _FakeUnitOfWork()
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert first.status is ExecutionDispatchStatus.EXECUTED
    assert first.receipt is not None
    assert second.status is ExecutionDispatchStatus.EXECUTED
    assert second.receipt == first.receipt
    assert "idempotent duplicate" in second.reason
    assert broker.submit_calls == 1


def test_live_submission_failure_is_unknown_through_canonical_boundary() -> None:
    class FailingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise RuntimeError("transport timeout")

    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    unit_of_work = _FakeUnitOfWork()
    broker = FailingBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert result.status is ExecutionDispatchStatus.UNKNOWN
    assert result.receipt is None
    assert "reconciliation" in result.reason
    assert broker.submit_calls == 1


def test_live_unknown_receipt_preserves_pending_reservation() -> None:
    class UnknownBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            return ExecutionReceipt(
                request_id=uuid4(),
                client_order_id=request.order.client_order_id,
                outcome=ExecutionOutcome.UNKNOWN,
                order_status=OrderStatus.UNKNOWN,
                executed_at=request.order.created_at,
                simulated=False,
                source="fake-broker",
                account_id=self.connection.account_id,
                connection_id=self.connection.connection_id,
            )

    request = _live_request()
    broker = UnknownBroker()
    unit_of_work = _FakeUnitOfWork()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert first.status is ExecutionDispatchStatus.UNKNOWN
    assert first.receipt is not None
    assert first.receipt.outcome is ExecutionOutcome.UNKNOWN
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id,
        request_fingerprint(request),
    )
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None
    assert unit_of_work.receipts.get(first.receipt.receipt_id) is None

    second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert second.status is ExecutionDispatchStatus.UNKNOWN
    assert broker.submit_calls == 1


def test_live_unit_of_work_groups_receipt_and_completion() -> None:
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert unit_of_work.committed
    assert not unit_of_work.rolled_back
    assert unit_of_work.receipts.get(result.receipt.receipt_id) == result.receipt
    assert (
        unit_of_work.receipts.get_by_client_order(request.order.client_order_id) == result.receipt
    )
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.existing_receipt_id == result.receipt.receipt_id
    assert not decision.reservation_pending
    assert decision.pending_context is not None
    assert decision.pending_context.order == request.order
    assert decision.pending_context.execution_context == request.execution_context
    assert broker.submit_calls == 1


def test_live_unit_of_work_submit_failure_is_unknown_without_receipt() -> None:
    class FailingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise RuntimeError("transport timeout")

    request = _live_request()
    broker = FailingBroker()
    unit_of_work = _FakeUnitOfWork()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert result.status is ExecutionDispatchStatus.UNKNOWN
    assert result.receipt is None
    assert "reconciliation" in result.reason
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None
    assert unit_of_work.committed
    assert not unit_of_work.rolled_back
    assert broker.submit_calls == 1


def test_live_without_explicit_trading_gate_is_blocked() -> None:
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        policy_verifier=policy_verifier(),
    ).execute(
        request,
        broker=broker,
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "explicitly configured durable TradingGate" in result.reason
    assert broker.submit_calls == 0


def test_live_without_application_runtime_is_blocked() -> None:
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "ApplicationRuntime" in result.reason
    assert broker.submit_calls == 0


def test_live_with_unstarted_application_runtime_is_blocked() -> None:
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()

    class NoopRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        application_runtime=runtime,
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "started ApplicationRuntime" in result.reason
    assert broker.submit_calls == 0


def test_live_with_unresolved_recovery_is_blocked_without_submit() -> None:
    """A runtime that attempted startup with unresolved recovery stays unready,
    so LIVE orchestration blocks with no broker submission."""
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()

    class FailedRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun(
                (PendingRecoveryResult("order-1", False, error="broker unavailable"),)
            )

    runtime = ApplicationRuntime(pending_recovery=FailedRecovery())
    report = runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert report.ready is False
    assert not runtime.started

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        application_runtime=runtime,
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "started ApplicationRuntime" in result.reason
    assert broker.submit_calls == 0


_NESTED_ORDER_ID = UUID("00000000-0000-0000-0000-000000000002")
_NESTED_ORDER_ID_2 = UUID("00000000-0000-0000-0000-000000000003")
_NESTED_ORDER_KEY = str(_NESTED_ORDER_ID)
_NESTED_UNSET: object = object()
_NESTED_ACCOUNT_ID = AccountId("account-1")
_NESTED_CONNECTION_ID = BrokerConnectionId("connection-1")


def _nested_broker_observation(
    order_id: UUID = _NESTED_ORDER_ID,
    broker_order_id: str | None = "broker-1",
) -> OrderObservation:
    return OrderObservation(
        order_id=order_id,
        status=OrderStatus.ACCEPTED,
        requested_quantity="1",
        filled_quantity="0",
        broker_order_id=broker_order_id,
        account_id=_NESTED_ACCOUNT_ID,
        connection_id=_NESTED_CONNECTION_ID,
    )


def _matched_nested_result(**overrides: object) -> OrderStateReconciliationResult:
    base: dict[str, object] = {
        "order_id": _NESTED_ORDER_ID,
        "account_id": _NESTED_ACCOUNT_ID,
        "connection_id": _NESTED_CONNECTION_ID,
        "broker_order_id": "broker-1",
        "order": OrderReconciliationResult(
            _NESTED_ORDER_ID, OrderReconciliationStatus.MATCHED, "order state matches"
        ),
        "position": PositionReconciliation(
            _NESTED_ACCOUNT_ID,
            _NESTED_CONNECTION_ID,
            "NSE:TCS",
            PositionReconciliationStatus.MATCHED,
            Decimal("1"),
            Decimal("1"),
            datetime(2026, 1, 1, tzinfo=UTC),
            "position quantity reconciled",
        ),
        "account": ReconciliationReport(
            _NESTED_ACCOUNT_ID,
            _NESTED_CONNECTION_ID,
            AccountReconciliationStatus.MATCHED,
            (),
        ),
        "status": OrderWorkflowStatus.MATCHED,
        "reasons": (),
        "identity_error": None,
    }
    base.update(overrides)
    return OrderStateReconciliationResult(**base)


def _nested_position(
    status: PositionReconciliationStatus,
    account_id: AccountId = _NESTED_ACCOUNT_ID,
) -> PositionReconciliation:
    return PositionReconciliation(
        account_id,
        _NESTED_CONNECTION_ID,
        "NSE:TCS",
        status,
        Decimal("1"),
        Decimal("1"),
        datetime(2026, 1, 1, tzinfo=UTC),
        "position evidence",
    )


def _advisory_nested_account(
    field: object = "available_cash",
    expected: object = "100",
    observed: object = "101",
    account_id: AccountId = _NESTED_ACCOUNT_ID,
    connection_id: BrokerConnectionId = _NESTED_CONNECTION_ID,
) -> ReconciliationReport:
    finding = ReconciliationFinding(field, expected, observed, "balance delta")  # type: ignore[arg-type]
    return ReconciliationReport(
        account_id,
        connection_id,
        AccountReconciliationStatus.MISMATCH,
        (finding,),
    )


def _definitive_nested_outcome(
    result: object,
    broker_order: object = _NESTED_UNSET,
) -> EvidenceRefreshOutcome:
    if broker_order is _NESTED_UNSET:
        broker_order = _nested_broker_observation()
    return EvidenceRefreshOutcome(
        result=result,
        attempts=0,
        refreshed_domains=(),
        definitive=True,
        broker_order=broker_order,
    )


@pytest.mark.parametrize(
    "report",
    [
        PendingRecoveryRun((PendingRecoveryResult(_NESTED_ORDER_KEY, True),)),
        PendingRecoveryRun(results=[PendingRecoveryResult("order-1", False)]),
        PendingRecoveryRun((PendingRecoveryResult("order-1", False), object())),
        PendingRecoveryRun((PendingRecoveryResult("order-1", 1),)),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY, True, outcome=_definitive_nested_outcome(None)
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(status=OrderWorkflowStatus.UNKNOWN)
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    None,
                    True,
                    outcome=_definitive_nested_outcome(_matched_nested_result()),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(_matched_nested_result(order=None)),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            identity_error=(
                                "broker order identity does not match execution receipt"
                            ),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            position=_nested_position(PositionReconciliationStatus.INCOMPLETE),
                            account=_advisory_nested_account(),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            position=_nested_position(PositionReconciliationStatus.MISMATCH),
                            account=_advisory_nested_account(),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(status=OrderWorkflowStatus.MISMATCH)
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(expected=None),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(observed=Decimal("101")),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(expected=""),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(field=[]),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(observed="100"),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(observed="1E2"),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(observed="Infinity"),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(expected="-100"),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(expected=" 100 "),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            account=_advisory_nested_account(account_id=AccountId("account-2")),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            status=OrderWorkflowStatus.MISMATCH,
                            position=_nested_position(
                                PositionReconciliationStatus.MATCHED,
                                account_id=AccountId("account-2"),
                            ),
                            account=_advisory_nested_account(),
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            order=OrderReconciliationResult(
                                _NESTED_ORDER_ID_2,
                                OrderReconciliationStatus.MATCHED,
                                "order state matches",
                            )
                        )
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    str(_NESTED_ORDER_ID_2),
                    True,
                    outcome=_definitive_nested_outcome(_matched_nested_result()),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(),
                        broker_order=_nested_broker_observation(order_id=_NESTED_ORDER_ID_2),
                    ),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(_matched_nested_result(), broker_order=None),
                ),
            )
        ),
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    _NESTED_ORDER_KEY,
                    True,
                    outcome=_definitive_nested_outcome(
                        _matched_nested_result(
                            order=OrderReconciliationResult(
                                "not-a-uuid",  # type: ignore[arg-type]
                                OrderReconciliationStatus.MATCHED,
                                "order state matches",
                            )
                        )
                    ),
                ),
            )
        ),
    ],
    ids=[
        "definitive-without-outcome-evidence",
        "list-results-container",
        "malformed-result-element",
        "non-bool-definitive",
        "nested-result-none",
        "nested-status-unknown",
        "malformed-identity",
        "matched-without-order",
        "mismatch-with-identity-error",
        "mismatch-with-unresolved-position",
        "mismatch-with-unmatched-position",
        "mismatch-with-matched-account",
        "advisory-half-sided-finding",
        "advisory-non-string-observed",
        "advisory-empty-expected",
        "advisory-unhashable-field",
        "advisory-equal-amounts",
        "advisory-numeric-equal-amounts",
        "advisory-non-finite-observed",
        "advisory-negative-expected",
        "advisory-non-canonical-format",
        "advisory-account-scope-conflict",
        "advisory-position-scope-conflict",
        "nested-order-identity-conflict",
        "record-order-identity-conflict",
        "broker-observation-order-conflict",
        "missing-broker-observation",
        "malformed-nested-order-identity",
    ],
)
def test_live_with_malformed_recovery_report_is_blocked_without_submit(
    report: PendingRecoveryRun,
) -> None:
    """A malformed recovery report never starts the runtime, so LIVE
    orchestration blocks before any broker submission."""
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()

    class MalformedRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return report

    runtime = ApplicationRuntime(pending_recovery=MalformedRecovery())
    startup = runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert startup.ready is False
    assert not runtime.started

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        application_runtime=runtime,
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "started ApplicationRuntime" in result.reason
    assert broker.submit_calls == 0


def test_live_gate_block_not_blocked_by_slow_broker() -> None:
    """
    R0-B: trading_gate.block() must not be indefinitely serialized behind
    a slow broker.submit() call. The gate lock is released before the broker call.
    """
    request = _live_request()
    gate = _durable_gate()
    unit_of_work = _FakeUnitOfWork()
    submit_started = Event()
    release_submit = Event()
    block_complete = Event()
    outcome = {}

    class BlockingBroker(FakeBroker):
        def submit(self, request):
            submit_started.set()
            if not release_submit.wait(timeout=5):
                raise AssertionError("submission release event was not signalled")
            return super().submit(request)

    broker = BlockingBroker()
    orchestrator = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        application_runtime=_started_runtime(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    def run_execution() -> None:
        outcome["result"] = _execute_admitted_transaction(
            orchestrator, request, broker, unit_of_work
        )

    def block_gate() -> None:
        gate.block("operator emergency stop")
        block_complete.set()

    execute_thread = Thread(target=run_execution)
    block_thread = Thread(target=block_gate)
    execute_thread.start()
    assert submit_started.wait(timeout=5)

    block_thread.start()
    # Gate block should return immediately, not wait for the slow broker
    assert block_complete.wait(timeout=0.5)

    release_submit.set()
    execute_thread.join(timeout=5)
    block_thread.join(timeout=5)

    assert not execute_thread.is_alive()
    assert not block_thread.is_alive()
    # Execution should complete (EXECUTED or UNKNOWN depending on timing)
    assert outcome["result"].status in (
        ExecutionDispatchStatus.EXECUTED,
        ExecutionDispatchStatus.UNKNOWN,
    )
    assert broker.submit_calls == 1
    assert gate.allow() is False


def test_live_without_unit_of_work_is_blocked() -> None:
    request = _live_request()
    broker = FakeBroker()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable UnitOfWork" in result.reason
    assert broker.submit_calls == 0


class _CountingProbeBroker(FakeBroker):
    """Broker double with independent counters for every pre-submit probe."""

    def __init__(self) -> None:
        super().__init__()
        self.health_calls = 0
        self.instrument_calls = 0
        self.capabilities_calls = 0

    def health(self):
        self.health_calls += 1
        return super().health()

    def instrument(self, instrument_id):
        self.instrument_calls += 1
        return super().instrument(instrument_id)

    def capabilities(self):
        self.capabilities_calls += 1
        return super().capabilities()


def test_live_without_submission_quarantine_is_blocked_without_submit() -> None:
    """LIVE admission requires the durable quarantine capability.

    Without it, an uncertain post-admission outcome could not preserve
    unresolved submission evidence; the submission is denied at the
    earliest LIVE admission boundary — before any broker-specific probe
    (connection, health, instrument, capabilities), before any durable
    reservation exists, and before the broker can be contacted.
    """
    request = _live_request()
    broker = _CountingProbeBroker()
    unit_of_work = _FakeUnitOfWork()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable submission quarantine repository" in result.reason
    assert broker.health_calls == 0
    assert broker.instrument_calls == 0
    assert broker.capabilities_calls == 0
    assert broker.submit_calls == 0
    fingerprint = request_fingerprint(request)
    decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
    assert decision.reservation_pending is False
    assert decision.existing_receipt_id is None
    assert decision.operator_resolved is False
    assert decision.not_submitted_resolution is None
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None


def test_paper_execution_does_not_require_submission_quarantine() -> None:
    """The quarantine binding is exactly the LIVE admission boundary."""
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        paper_executor=FakePaperExecutor(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    request = _request(ExecutionMode.PAPER)
    snapshot = Quote(
        instrument=request.order.instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )

    result = orchestrator.execute(request, snapshot=snapshot)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None


def test_live_rejects_process_local_trading_gate() -> None:
    request = _live_request()
    broker = FakeBroker()
    gate = TradingGate()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=gate,
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable TradingGate" in result.reason
    assert broker.submit_calls == 0


def test_live_unit_of_work_duplicate_returns_persisted_receipt() -> None:
    request = _live_request()
    broker = FakeBroker()
    unit_of_work = _FakeUnitOfWork()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert first.status is ExecutionDispatchStatus.EXECUTED
    assert first.receipt is not None

    second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert second.status is ExecutionDispatchStatus.EXECUTED
    assert second.receipt == first.receipt
    assert "idempotent duplicate" in second.reason
    assert broker.submit_calls == 1


def _sqlite_setup(tmp_path):
    database = SqliteDatabase(tmp_path / "quantx.db")
    unit_of_work = SqliteUnitOfWork(database)
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=DurableTradingGate(
            SqliteTradingGateStateStore(database), default_enabled=True
        ),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        submission_quarantine=SqliteSubmissionQuarantineRepository(database),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    )
    return database, unit_of_work, orchestrator


def test_sqlite_first_execution_persists_receipt_and_completion(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert result.receipt is not None
        assert broker.submit_calls == 1
        assert unit_of_work.receipts.get(result.receipt.receipt_id) == result.receipt
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.existing_receipt_id == result.receipt.receipt_id
        assert not decision.reservation_pending
    finally:
        database.close()


def test_sqlite_duplicate_returns_persisted_receipt_without_resubmit(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()
        first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert first.status is ExecutionDispatchStatus.EXECUTED
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.EXECUTED
        assert second.receipt == first.receipt
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_submission_failure_preserves_pending_without_retry(tmp_path) -> None:
    class FailingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise RuntimeError("transport timeout")

    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FailingBroker()
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert "reconciliation" in result.reason
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_fingerprint_mismatch_rejected_without_submit(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()
        first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert first.status is ExecutionDispatchStatus.EXECUTED
        changed_order = replace(request.order, quantity=Decimal("11"))
        changed_request = replace(request, order=changed_order)
        with pytest.raises(ValueError, match="different request"):
            _execute_admitted_transaction(
                orchestrator, changed_request, broker, unit_of_work
            )
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_complete_survives_restart_proxy(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    request = _live_request()
    database_a = SqliteDatabase(path)
    try:
        unit_of_work_a = SqliteUnitOfWork(database_a)
        orchestrator_a = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=unit_of_work_a,
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database_a), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database_a),
            live_risk_evaluator=_approving_live_risk_evaluator(),
            policy_verifier=policy_verifier(),
        )
        broker_a = FakeBroker()
        first = _execute_admitted_transaction(
            orchestrator_a, request, broker_a, unit_of_work_a
        )
        assert first.status is ExecutionDispatchStatus.EXECUTED
        assert first.receipt is not None
        assert broker_a.submit_calls == 1
    finally:
        database_a.close()

    database_b = SqliteDatabase(path)
    try:
        unit_of_work_b = SqliteUnitOfWork(database_b)
        broker_b = FakeBroker()
        orchestrator_b = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=unit_of_work_b,
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database_b), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database_b),
            live_risk_evaluator=_approving_live_risk_evaluator(),
            policy_verifier=policy_verifier(),
        )
        second = _execute_admitted_transaction(
            orchestrator_b, request, broker_b, unit_of_work_b
        )
        assert second.status is ExecutionDispatchStatus.EXECUTED
        assert second.receipt == first.receipt
        assert broker_b.submit_calls == 0
    finally:
        database_b.close()


def test_sqlite_completion_failure_is_unknown_with_pending(tmp_path, monkeypatch) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()

        def boom(*args, **kwargs):
            raise RuntimeError("completion unavailable")

        monkeypatch.setattr(unit_of_work.idempotency, "complete", boom)
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is not None
        assert "reconciliation" in result.reason
        persisted = unit_of_work.receipts.get_by_client_order(request.order.client_order_id)
        assert persisted is not None
        assert persisted.receipt_id == result.receipt.receipt_id
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        assert broker.submit_calls == 1
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_live_without_unit_of_work_does_not_submit() -> None:
    request = _live_request()
    broker = FakeBroker()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable UnitOfWork" in result.reason
    assert broker.submit_calls == 0


def test_broker_submit_runs_outside_sqlite_transaction(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        observed = {}

        class InspectingBroker(FakeBroker):
            def submit(self, request):
                observed["in_transaction"] = database.connection().in_transaction
                return super().submit(request)

        broker = InspectingBroker()
        result = _execute_admitted_transaction(
            orchestrator, _live_request(), broker, unit_of_work
        )
        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert observed["in_transaction"] is False
    finally:
        database.close()


def test_partial_continuation_is_blocked_by_trading_gate_before_adapter() -> None:
    from quantx.execution.receipts.lifecycle import ExecutionLifecycle

    request = _request(ExecutionMode.PAPER)
    lifecycle = ExecutionLifecycle(
        request.order.client_order_id,
        Decimal("10"),
        Decimal("4"),
        OrderStatus.PARTIALLY_FILLED,
    )
    gate = TradingGate()
    gate.block("risk limit reached")

    class Adapter(FakePaperExecutor):
        def continue_partial(self, *args, **kwargs):
            raise AssertionError("continuation adapter must not be called")

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        paper_executor=Adapter(),
        trading_gate=gate,
        policy_verifier=policy_verifier(),
    ).continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=Quote(
            instrument=request.order.instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            ask=Decimal("100"),
        ),
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "trading is blocked" in result.reason


def test_partial_continuation_passes_control_plane_to_adapter() -> None:
    from quantx.execution.receipts.lifecycle import ExecutionLifecycle

    request = _request(ExecutionMode.PAPER)
    lifecycle = ExecutionLifecycle(
        request.order.client_order_id,
        Decimal("10"),
        Decimal("4"),
        OrderStatus.PARTIALLY_FILLED,
    )
    snapshot = Quote(
        instrument=request.order.instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )

    class Adapter(FakePaperExecutor):
        def __init__(self):
            self.called = False

        def continue_partial(
            self, request, lifecycle, *, risk_result, snapshot, requested_quantity=None
        ):
            self.called = True
            assert risk_result.decision is RiskDecision.APPROVE
            fill = Fill(
                client_order_id=request.order.client_order_id,
                instrument=request.order.instrument,
                side=request.order.side,
                quantity=Decimal("1"),
                price=snapshot.ask,
                filled_at=snapshot.timestamp,
            )
            return ExecutionReceipt(
                request_id=uuid4(),
                client_order_id=request.order.client_order_id,
                outcome=ExecutionOutcome.PARTIALLY_FILLED,
                order_status=OrderStatus.PARTIALLY_FILLED,
                executed_at=snapshot.timestamp,
                fills=(fill,),
                simulated=True,
                source="continuation-test",
                order_quantity=request.order.quantity,
            )

    adapter = Adapter()
    result = ExecutionOrchestrator(
        paper_executor=adapter,
        policy_verifier=policy_verifier(),
    ).continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=snapshot,
    )

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert adapter.called


class _AdmissionGatedGate(DurableTradingGate):
    """Durable gate whose submit admission waits on an event first.

    The wait happens outside every gate/store lock, so ``block()`` from
    another thread is never delayed by the paused admission.
    """

    def __init__(self, store, *, admission_release: Event) -> None:
        super().__init__(store, default_enabled=True)
        self._admission_release = admission_release

    def admit_submission(self) -> bool:
        assert self._admission_release.wait(timeout=10)
        return super().admit_submission()


def _wait_for_reservation(unit_of_work, request) -> None:
    """Poll until the reservation is durable; fail loudly instead of hanging."""
    import time

    start = time.monotonic()
    while True:
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        if decision.reservation_pending:
            return
        assert time.monotonic() - start < 10, "reservation never became durable"


def test_live_block_before_submit_admission_denies_without_submit() -> None:
    """Once block() returns, a reserved-but-unadmitted submission is denied.

    The read-only broker observations (connection, health, instrument) run
    before the reservation and admission boundary, so the denial contract is
    exactly "never ``broker.submit()``" — not "never any broker contact".
    """
    admission_release = Event()
    gate = _AdmissionGatedGate(InMemoryTradingGateStateStore(), admission_release=admission_release)
    unit_of_work = _FakeUnitOfWork()
    broker = _CountingProbeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    request = _live_request()
    outcome: dict = {}

    def run_execute() -> None:
        try:
            outcome["result"] = _execute_admitted_transaction(
                orchestrator, request, broker, unit_of_work
            )
        except BaseException as exc:
            outcome["error"] = exc

    worker = Thread(target=run_execute)
    worker.start()
    try:
        _wait_for_reservation(unit_of_work, request)
        gate.block("operator emergency stop")
        admission_release.set()
        worker.join(timeout=10)
    finally:
        admission_release.set()
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert "error" not in outcome

    result = outcome["result"]
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "trading is blocked: operator emergency stop" in result.reason
    assert broker.health_calls >= 1
    assert broker.instrument_calls >= 1
    assert broker.submit_calls == 0
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None

    retry_while_blocked = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert retry_while_blocked.status is ExecutionDispatchStatus.BLOCKED
    assert broker.submit_calls == 0

    gate.enable()
    retry_after_enable = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert retry_after_enable.status is ExecutionDispatchStatus.UNKNOWN
    assert broker.submit_calls == 0


class _HangingBroker(FakeBroker):
    """Broker that stays inside the submit call until released."""

    def __init__(self, *, submit_entered: Event, submit_release: Event) -> None:
        super().__init__()
        self._submit_entered = submit_entered
        self._submit_release = submit_release

    def submit(self, request):
        self._submit_entered.set()
        assert self._submit_release.wait(timeout=10)
        return super().submit(request)


def test_live_block_during_inflight_submit_neither_cancels_nor_waits() -> None:
    """A block() landing during an admitted broker call changes nothing.

    ``block()`` must return while the broker call is still hung (it never
    waits for broker I/O), and the admitted submission keeps its genuine
    broker outcome instead of being misrepresented as cancelled or blocked.
    """
    submit_entered = Event()
    submit_release = Event()
    gate = _durable_gate()
    unit_of_work = _FakeUnitOfWork()
    broker = _HangingBroker(submit_entered=submit_entered, submit_release=submit_release)
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    request = _live_request()
    outcome: dict = {}

    def run_execute() -> None:
        try:
            outcome["result"] = _execute_admitted_transaction(
                orchestrator, request, broker, unit_of_work
            )
        except BaseException as exc:
            outcome["error"] = exc

    worker = Thread(target=run_execute)
    worker.start()
    try:
        assert submit_entered.wait(timeout=10)
        gate.block("operator emergency stop")
        assert worker.is_alive()
        submit_release.set()
        worker.join(timeout=10)
    finally:
        submit_release.set()
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert "error" not in outcome

    result = outcome["result"]
    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert broker.submit_calls == 1
    assert "blocked" not in result.reason.lower()
    assert "cancel" not in result.reason.lower()


def _sqlite_setup_with_quarantine(tmp_path):
    database = SqliteDatabase(tmp_path / "quantx.db")
    unit_of_work = SqliteUnitOfWork(database)
    quarantine = SqliteSubmissionQuarantineRepository(database)
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=DurableTradingGate(
            SqliteTradingGateStateStore(database), default_enabled=True
        ),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        submission_quarantine=quarantine,
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    )
    return database, unit_of_work, orchestrator, quarantine


def _foreign_receipt(request: ApprovedExecutionRequest) -> ExecutionReceipt:
    """A well-formed receipt that is not bound to the approved request."""
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime.now(UTC),
        simulated=False,
        source="foreign-broker",
        broker_order_id="BR-FOREIGN-1",
        correlation_id="foreign-correlation",
        order_id=uuid4(),
        account_id=AccountId("other-account"),
        connection_id=BrokerConnectionId("other-conn"),
    )


def _unknown_broker_receipt(request: ApprovedExecutionRequest) -> ExecutionReceipt:
    """A bound receipt whose broker outcome is explicitly UNKNOWN."""
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=OrderStatus.UNKNOWN,
        executed_at=datetime.now(UTC),
        simulated=False,
        source="fake-broker",
        broker_order_id="BR-UNKNOWN-1",
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )


class _FixedReceiptBroker(FakeBroker):
    """Broker that returns a fixed receipt instead of a bound accepted one."""

    def __init__(self, receipt: ExecutionReceipt) -> None:
        super().__init__()
        self._receipt = receipt

    def submit(self, request):
        self.submit_calls += 1
        return self._receipt


class _CommitFailingUnitOfWork:
    """Delegates to a real UnitOfWork; the third clean commit boundary fails.

    The LIVE flow opens three transactions (pre-check, reservation,
    receipt save + completion); failing only the final commit models a
    persistence fault exactly after the broker may have accepted.
    """

    def __init__(self, inner: SqliteUnitOfWork) -> None:
        self._inner = inner
        self._clean_exits = 0

    @property
    def idempotency(self):
        return self._inner.idempotency

    @property
    def receipts(self):
        return self._inner.receipts

    def commit(self) -> None:
        self._inner.commit()

    def rollback(self) -> None:
        self._inner.rollback()

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self._clean_exits += 1
            if self._clean_exits == 3:
                failure = RuntimeError("simulated commit boundary failure")
                self._inner.__exit__(type(failure), failure, failure.__traceback__)
                raise AssertionError("commit failure was not propagated")
        self._inner.__exit__(exc_type, exc_value, traceback)


def _quarantine_orchestrator(database, *, gate=None):
    unit_of_work = SqliteUnitOfWork(database)
    quarantine = SqliteSubmissionQuarantineRepository(database)
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate
        or DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        submission_quarantine=quarantine,
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    )
    return unit_of_work, quarantine, orchestrator


def test_sqlite_receipt_save_failure_is_unknown_with_quarantined_evidence(
    tmp_path, monkeypatch
) -> None:
    database, unit_of_work, orchestrator, quarantine = _sqlite_setup_with_quarantine(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()

        def failing_save(receipt):
            raise RuntimeError("receipt storage unavailable")

        monkeypatch.setattr(unit_of_work.receipts, "save", failing_save)
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert "reconciliation" in result.reason
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN
        assert observation.source == "fake-broker"
        assert observation.outcome == "ACCEPTED"
        assert observation.order_status == "ACCEPTED"
        assert observation.observed_at.tzinfo is not None
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_commit_boundary_failure_is_unknown_not_false_success(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        real_unit_of_work = SqliteUnitOfWork(database)
        unit_of_work = _CommitFailingUnitOfWork(real_unit_of_work)
        quarantine = SqliteSubmissionQuarantineRepository(database)
        orchestrator = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=unit_of_work,
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            submission_quarantine=quarantine,
            live_risk_evaluator=_approving_live_risk_evaluator(),
            policy_verifier=policy_verifier(),
        )
        request = _live_request()
        broker = FakeBroker()
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert "uncertain" in result.reason
        assert "reconciliation" in result.reason
        assert real_unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = real_unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        assert observations[0].kind is QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_completion_failure_receipt_durable_across_reopen(tmp_path, monkeypatch) -> None:
    path = tmp_path / "quantx.db"
    request = _live_request()
    database = SqliteDatabase(path)
    try:
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database)
        broker = FakeBroker()

        def boom(*args, **kwargs):
            raise RuntimeError("completion unavailable")

        monkeypatch.setattr(unit_of_work.idempotency, "complete", boom)
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is not None
        assert "reconciliation" in result.reason
        assert broker.submit_calls == 1
        persisted = unit_of_work.receipts.get_by_client_order(request.order.client_order_id)
        assert persisted is not None
        assert persisted.receipt_id == result.receipt.receipt_id
        assert quarantine.list_by_client_order(request.order.client_order_id) == ()
    finally:
        database.close()

    database_b = SqliteDatabase(path)
    try:
        unit_of_work_b, _, orchestrator_b = _quarantine_orchestrator(database_b)
        persisted = unit_of_work_b.receipts.get_by_client_order(request.order.client_order_id)
        assert persisted is not None
        assert persisted.receipt_id == result.receipt.receipt_id
        decision = unit_of_work_b.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        broker_b = FakeBroker()
        replay = _execute_admitted_transaction(
            orchestrator_b, request, broker_b, unit_of_work_b
        )
        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker_b.submit_calls == 0
    finally:
        database_b.close()


def test_sqlite_foreign_receipt_quarantined_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    request = _live_request()
    database = SqliteDatabase(path)
    try:
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database)
        broker = _FixedReceiptBroker(_foreign_receipt(request))
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert "identity mismatch" in result.reason
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        assert broker.submit_calls == 1
    finally:
        database.close()

    database_b = SqliteDatabase(path)
    try:
        quarantine_b = SqliteSubmissionQuarantineRepository(database_b)
        unit_of_work_b = SqliteUnitOfWork(database_b)
        observations = quarantine_b.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.IDENTITY_REJECTED
        assert observation.broker_order_id == "BR-FOREIGN-1"
        assert observation.source == "foreign-broker"
        assert observation.request_correlation_id == request.correlation_id
        assert observation.outcome == "ACCEPTED"
        assert observation.order_status == "ACCEPTED"
        assert observation.observed_at.tzinfo is not None
        assert "client_order_id" in observation.reason
        decision = unit_of_work_b.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
    finally:
        database_b.close()


def test_sqlite_unknown_receipt_quarantined_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    request = _live_request()
    database = SqliteDatabase(path)
    try:
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database)
        broker = _FixedReceiptBroker(_unknown_broker_receipt(request))
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is not None
        assert result.receipt.outcome is ExecutionOutcome.UNKNOWN
        assert "broker returned an UNKNOWN receipt" in result.reason
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        assert broker.submit_calls == 1
    finally:
        database.close()

    database_b = SqliteDatabase(path)
    try:
        quarantine_b = SqliteSubmissionQuarantineRepository(database_b)
        observations = quarantine_b.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.BROKER_UNKNOWN
        assert observation.broker_order_id == "BR-UNKNOWN-1"
        assert observation.source == "fake-broker"
        assert observation.request_correlation_id == request.correlation_id
        assert observation.outcome == "UNKNOWN"
        assert observation.order_status == "UNKNOWN"
        assert observation.observed_at.tzinfo is not None
    finally:
        database_b.close()


def test_sqlite_transport_failure_after_send_is_unknown_with_quarantine(tmp_path) -> None:
    class FailingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise RuntimeError("connection reset mid-flight")

    database, unit_of_work, orchestrator, quarantine = _sqlite_setup_with_quarantine(tmp_path)
    try:
        request = _live_request()
        broker = FailingBroker()
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert broker.submit_calls == 1
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        assert observations[0].kind is QuarantineObservationKind.TRANSPORT_UNCERTAIN
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        second = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_dual_persistence_failure_latches_safety_fault_and_blocks_submission(
    tmp_path, monkeypatch
) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate_store = SqliteTradingGateStateStore(database)
        gate = DurableTradingGate(gate_store, default_enabled=True)
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database, gate=gate)
        request = _live_request()
        broker = FakeBroker()

        def failing_save(receipt):
            raise RuntimeError("receipt storage unavailable")

        def failing_record(observation):
            raise RuntimeError("quarantine storage unavailable")

        monkeypatch.setattr(unit_of_work.receipts, "save", failing_save)
        monkeypatch.setattr(quarantine, "record", failing_record)
        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert "submissions are disabled pending reconciliation" in result.reason
        assert gate.allow() is False
        persisted = gate_store.load()
        assert persisted is not None
        assert persisted.enabled is False
        assert broker.submit_calls == 1
        second = orchestrator.execute(request, broker=broker)
        assert second.status is ExecutionDispatchStatus.BLOCKED
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_quarantine_record_failure_latches_fault_without_permissive_path() -> None:
    """A failing quarantine recorder must not leave a permissive path.

    The uncertainty stays UNKNOWN, the pending reservation stays pending
    for reconciliation, the safety fault disables further submission, and
    a replay never resubmits.
    """

    class FailingQuarantine(_FakeSubmissionQuarantine):
        def record(self, observation) -> None:
            raise RuntimeError("quarantine storage unavailable")

    class FailingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise RuntimeError("transport timeout")

    request = _live_request()
    broker = FailingBroker()
    unit_of_work = _FakeUnitOfWork()
    gate = _durable_gate()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=FailingQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert first.status is ExecutionDispatchStatus.UNKNOWN
    assert "submission evidence persistence failed" in first.reason
    assert "submissions are disabled pending reconciliation" in first.reason
    assert gate.allow() is False
    assert broker.submit_calls == 1
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None

    replay = orchestrator.execute(request, broker=broker)

    assert replay.status is ExecutionDispatchStatus.BLOCKED
    assert "trading is blocked" in replay.reason
    assert broker.submit_calls == 1


def test_preflight_rejection_is_typed_not_submitted_without_operator_record() -> None:
    """A definite preflight rejection is a typed local closure, not a human one."""

    class PreflightRejectingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise BrokerPreflightRejected("order validity DAY/IOC is not supported")

    request = _live_request()
    broker = PreflightRejectingBroker()
    unit_of_work = _FakeUnitOfWork()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    fingerprint = request_fingerprint(request)

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert first.status is ExecutionDispatchStatus.BLOCKED
    assert "submission was not sent" in first.reason
    assert broker.submit_calls == 1
    decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
    resolution = decision.not_submitted_resolution
    assert resolution is not None
    assert resolution.source is NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION
    assert decision.reservation_pending is False
    assert decision.operator_resolved is False
    assert decision.operator_resolution is None
    assert (
        unit_of_work.idempotency.get_operator_resolution(request.order.client_order_id, fingerprint)
        is None
    )
    pending_ids = {
        record.client_order_id
        for record in unit_of_work.idempotency.list_pending_recovery_records()
    }
    assert str(request.order.client_order_id) not in pending_ids

    replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert replay.status is ExecutionDispatchStatus.BLOCKED
    assert "durably closed as not submitted" in replay.reason
    assert broker.submit_calls == 1


def test_preflight_rejection_closure_failure_is_unresolved_without_resubmit(monkeypatch) -> None:
    """If the typed closure cannot be persisted, the outcome stays UNKNOWN.

    The pending reservation is kept for reconciliation; the system never
    claims a not-submitted closure it could not record and never resubmits.
    """

    class PreflightRejectingBroker(FakeBroker):
        def submit(self, request):
            self.submit_calls += 1
            raise BrokerPreflightRejected("order validity DAY/IOC is not supported")

    request = _live_request()
    broker = PreflightRejectingBroker()
    unit_of_work = _FakeUnitOfWork()

    def failing_record_not_submitted(*args, **kwargs):
        raise RuntimeError("idempotency storage unavailable")

    monkeypatch.setattr(
        unit_of_work.idempotency, "record_not_submitted", failing_record_not_submitted
    )
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )

    first = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert first.status is ExecutionDispatchStatus.UNKNOWN
    assert "durable closure of the reservation failed" in first.reason
    assert broker.submit_calls == 1
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending
    assert decision.not_submitted_resolution is None
    assert decision.operator_resolved is False

    replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert replay.status is ExecutionDispatchStatus.UNKNOWN
    assert broker.submit_calls == 1


class _ArbitraryResponseBroker(FakeBroker):
    """Broker double returning an arbitrary (possibly malformed) response."""

    def __init__(self, response: object) -> None:
        super().__init__()
        self._response = response

    def submit(self, request):
        self.submit_calls += 1
        return self._response


def test_malformed_receipt_shape_after_submit_is_unknown_not_raised(tmp_path) -> None:
    """A broker response outside the receipt contract cannot escape as an exception.

    Once submission may have reached the broker, a malformed runtime shape
    must be reported as explicit UNKNOWN with the pending reservation kept
    and sanitized evidence retained, never as an exception implying a known
    outcome, and never as an automatic retry.
    """
    database, unit_of_work, orchestrator, quarantine = _sqlite_setup_with_quarantine(tmp_path)
    try:
        request = _live_request()
        broker = _ArbitraryResponseBroker(object())

        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert "reconciliation" in result.reason
        assert broker.submit_calls == 1
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.MALFORMED_RECEIPT
        assert observation.request_correlation_id == request.correlation_id
        assert observation.broker_order_id is None
        assert observation.source is None
        assert observation.outcome is None
        assert observation.order_status is None

        replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_malformed_receipt_runtime_enum_is_unknown_and_sanitized(tmp_path) -> None:
    """A receipt carrying malformed runtime enums never becomes canonical.

    The dataclass accepts arbitrary runtime values, so a hostile or broken
    adapter can hand back a receipt whose outcome/status are plain strings.
    That response must be quarantined as malformed evidence, reported
    UNKNOWN, and kept out of canonical receipts and idempotency completion.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database, gate=gate)
        request = _live_request()
        malformed = ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=cast(ExecutionOutcome, "ACCEPTED"),
            order_status=cast(OrderStatus, "ACCEPTED"),
            executed_at=datetime.now(UTC),
            simulated=False,
            source="fake-broker",
            broker_order_id="BR-CORRUPT-1",
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            order_quantity=request.order.quantity,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )
        broker = _ArbitraryResponseBroker(malformed)

        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert broker.submit_calls == 1
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.MALFORMED_RECEIPT
        assert observation.source == "fake-broker"
        assert observation.broker_order_id == "BR-CORRUPT-1"
        assert observation.request_correlation_id == request.correlation_id
        assert observation.outcome is None
        assert observation.order_status is None
        # Evidence was retained, so the fail-closed admission fault is not latched.
        assert gate.allow() is True

        replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_receipt_serialization_failure_after_submit_is_unknown_with_quarantine(
    tmp_path,
) -> None:
    """A canonical receipt that cannot be serialized is still an explicit UNKNOWN.

    Serialization happens after the broker may have accepted, so the
    failure must not escape. The pending reservation stays, sanitized
    evidence is quarantined, and a replay never resubmits.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database, gate=gate)
        request = _live_request()
        unserializable = ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=datetime.now(UTC),
            simulated=False,
            source="fake-broker",
            message=cast(str, object()),
            broker_order_id="BR-UNSERIALIZABLE-1",
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            order_quantity=request.order.quantity,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )
        broker = _ArbitraryResponseBroker(unserializable)

        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert "post-submit persistence failed" in result.reason
        assert broker.submit_calls == 1
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        assert observations[0].kind is QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN
        assert observations[0].broker_order_id == "BR-UNSERIALIZABLE-1"
        assert gate.allow() is True

        replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


class _RaisingOutcomeReceipt(ExecutionReceipt):
    """Hostile plugin response whose outcome attribute raises on access."""

    @property
    def outcome(self):
        raise RuntimeError("hostile attribute access")


def test_hostile_receipt_attribute_access_cannot_escape_or_latch_fault(tmp_path) -> None:
    """A hostile response can neither crash the call nor force a gate latch.

    The response passes ``isinstance(receipt, ExecutionReceipt)`` but raises
    on attribute access. After the external submit may have started, that
    must still become explicit UNKNOWN with a sanitized observation (the
    raising field is dropped), never an exception escaping the public call
    and never a spurious admission safety-fault latch.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database, gate=gate)
        request = _live_request()
        hostile = object.__new__(_RaisingOutcomeReceipt)
        object.__setattr__(hostile, "receipt_id", uuid4())
        object.__setattr__(hostile, "client_order_id", request.order.client_order_id)
        object.__setattr__(hostile, "order_status", OrderStatus.ACCEPTED)
        object.__setattr__(hostile, "source", "fake-broker")
        object.__setattr__(hostile, "broker_order_id", "BR-HOSTILE-1")
        broker = _ArbitraryResponseBroker(hostile)

        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert broker.submit_calls == 1
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.MALFORMED_RECEIPT
        assert observation.outcome is None
        assert observation.order_status == "ACCEPTED"
        assert observation.source == "fake-broker"
        assert observation.broker_order_id == "BR-HOSTILE-1"
        # The observation was recorded, so no spurious admission fault.
        assert gate.allow() is True

        replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_uninitialized_enum_receipt_is_malformed_not_persisted(tmp_path) -> None:
    """An enum-class instance with an unreadable value is not canonical.

    A hostile response can carry a real ``OrderStatus`` class instance whose
    ``value`` lookup raises (uninitialized member). It passes ``isinstance``
    but canonical persistence reads ``.value``, so it must be rejected as
    MALFORMED at the shape boundary — before identity validation and any
    canonical write — with the observation recorded and no gate latch.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database, gate=gate)
        request = _live_request()
        receipt = ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=datetime.now(UTC),
            simulated=False,
            source="fake-broker",
            message="uninitialized enum member",
            broker_order_id="BR-ENUM-1",
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            order_quantity=request.order.quantity,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )
        object.__setattr__(receipt, "order_status", str.__new__(OrderStatus, "ACCEPTED"))
        broker = _ArbitraryResponseBroker(receipt)

        result = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert broker.submit_calls == 1
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        observation = observations[0]
        assert observation.kind is QuarantineObservationKind.MALFORMED_RECEIPT
        assert observation.order_status is None
        assert observation.outcome == ExecutionOutcome.ACCEPTED.value
        assert observation.source == "fake-broker"
        assert observation.broker_order_id == "BR-ENUM-1"
        # The observation was recorded, so no spurious admission fault.
        assert gate.allow() is True

        replay = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_quarantined_observations_never_become_authoritative(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work, quarantine, orchestrator = _quarantine_orchestrator(database)
        foreign_request = _live_request()
        foreign_broker = _FixedReceiptBroker(_foreign_receipt(foreign_request))
        foreign_result = _execute_admitted_transaction(
            orchestrator, foreign_request, foreign_broker, unit_of_work
        )
        assert foreign_result.status is ExecutionDispatchStatus.UNKNOWN
        assert foreign_broker.submit_calls == 1
        unknown_request = _live_request()
        unknown_broker = _FixedReceiptBroker(_unknown_broker_receipt(unknown_request))
        unknown_result = _execute_admitted_transaction(
            orchestrator, unknown_request, unknown_broker, unit_of_work
        )
        assert unknown_result.status is ExecutionDispatchStatus.UNKNOWN
        assert unknown_broker.submit_calls == 1

        for request in (foreign_request, unknown_request):
            assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
            decision = unit_of_work.idempotency.check(
                request.order.client_order_id, request_fingerprint(request)
            )
            assert decision.existing_receipt_id is None
            assert decision.reservation_pending
        pending_ids = {
            record.client_order_id
            for record in unit_of_work.idempotency.list_pending_recovery_records()
        }
        assert str(foreign_request.order.client_order_id) in pending_ids
        assert str(unknown_request.order.client_order_id) in pending_ids
        for request in (foreign_request, unknown_request):
            observations = quarantine.list_by_client_order(request.order.client_order_id)
            assert len(observations) == 1
            assert unit_of_work.receipts.get(observations[0].observation_id) is None
    finally:
        database.close()


class _CountingIdempotencyStore(InMemoryIdempotencyStore):
    def __init__(self) -> None:
        super().__init__()
        self.reserve_calls = 0
        self.check_calls = 0

    def reserve_or_get(self, *args, **kwargs):
        self.reserve_calls += 1
        return super().reserve_or_get(*args, **kwargs)

    def check(self, *args, **kwargs):
        self.check_calls += 1
        return super().check(*args, **kwargs)


class _CountingGate(DurableTradingGate):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.allow_calls = 0
        self.permit_calls = 0
        self.admit_calls = 0

    def allow(self) -> bool:
        self.allow_calls += 1
        return super().allow()

    def submission_permit(self):
        self.permit_calls += 1
        return super().submission_permit()

    def admit_submission(self) -> bool:
        self.admit_calls += 1
        return super().admit_submission()


def _live_risk_orchestrator(evaluator):
    store = _CountingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=evaluator,
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    return orchestrator, gate, store, broker, unit_of_work


def _live_callback_orchestrator(
    *,
    session_guard=None,
    trading_gate=None,
    market_policy=None,
):
    store = _CountingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    gate = trading_gate or _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        session_guard=session_guard,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=market_policy
        or india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    return orchestrator, gate, store, broker, unit_of_work


class _GateReportingDurability(_CountingGate):
    """Counting durable gate that can report a non-boolean declaration."""

    def __init__(self, is_durable: object) -> None:
        super().__init__(InMemoryTradingGateStateStore(), default_enabled=True)
        object.__setattr__(self, "is_durable", is_durable)


class _RuntimeReportingStarted:
    """Minimal runtime stand-in exposing a chosen started value."""

    def __init__(self, started: object) -> None:
        self.started = started


def _runtime_reporting(started: object) -> ApplicationRuntime:
    return cast(ApplicationRuntime, _RuntimeReportingStarted(started))


def _live_prerequisite_orchestrator(
    *,
    gate: _CountingGate,
    runtime: ApplicationRuntime,
) -> tuple[ExecutionOrchestrator, _CountingIdempotencyStore, FakeBroker]:
    store = _CountingIdempotencyStore()
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=runtime,
        unit_of_work=_FakeUnitOfWork(store),
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    return orchestrator, store, broker


def _assert_no_live_prerequisite_side_effects(
    gate: _CountingGate,
    store: _CountingIdempotencyStore,
    broker: FakeBroker,
) -> None:
    assert gate.allow_calls == 0
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0
    assert store.check_calls == 0
    assert broker.submit_calls == 0


class _ScriptedSessionGuard(SessionExecutionGuard):
    def __init__(self, result) -> None:
        self._result = result

    def check(self, mode):
        return self._result


class _ScriptedGate(DurableTradingGate):
    def __init__(
        self,
        *,
        allow_result=True,
        permit_result=True,
        admit_result=True,
    ) -> None:
        super().__init__(InMemoryTradingGateStateStore(), default_enabled=True)
        self._allow_result = allow_result
        self._permit_result = permit_result
        self._admit_result = admit_result
        self.allow_calls = 0
        self.permit_calls = 0
        self.admit_calls = 0

    def allow(self):
        self.allow_calls += 1
        return self._allow_result

    @contextmanager
    def submission_permit(self):
        self.permit_calls += 1
        yield self._permit_result

    def admit_submission(self):
        self.admit_calls += 1
        return self._admit_result


def _india_policy_with_core_session_guard() -> MarketPolicyConfig:
    policy = india_market_policy(
        session_evaluator=_approving_india_session_evaluator(),
        rule_evaluator=_approving_india_evaluator(),
    )
    return MarketPolicyConfig(
        regions=tuple(
            replace(region, replaces_session_guard=False)
            if region.region is MarketRegion.INDIA
            else region
            for region in policy.regions
        ),
        checks=policy.checks,
    )


def test_live_without_risk_evaluator_blocks_before_gate_reservation_and_broker() -> None:
    """A missing LIVE pre-trade risk evaluator is a fail-closed prerequisite.

    It must be established beside the other LIVE composition prerequisites,
    before any gate permit, idempotency reservation, or broker contact.
    """
    store = _CountingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    broker = FakeBroker(connection_id=BrokerConnectionId("conn-1"))

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "live execution requires a configured pre-trade risk evaluator"
    assert gate.allow_calls == 0
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


@pytest.mark.parametrize(
    "evaluator",
    [
        lambda request: None,
        lambda request: "approve",
        lambda request: object(),
        lambda request: RiskResult("approve", "malformed decision"),
        lambda request: RiskResult(RiskDecision.REJECT, object()),
    ],
    ids=[
        "none",
        "plain-string",
        "missing-decision",
        "wrong-decision-type",
        "wrong-reason-type",
    ],
)
def test_untrusted_live_risk_callback_is_rejected_before_invocation(evaluator) -> None:
    called = False

    def untrusted(request):
        nonlocal called
        called = True
        return evaluator(request)

    orchestrator, gate, store, broker, unit_of_work = _live_risk_orchestrator(untrusted)

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert called is False
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.check_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


@pytest.mark.parametrize(
    "result",
    [
        SessionGuardResult(allowed="false"),
        SessionGuardResult(allowed=1),
        SessionGuardResult(allowed=True, reason=object()),
        None,
        object(),
    ],
    ids=[
        "string-false",
        "integer-one",
        "wrong-reason-type",
        "none",
        "wrong-type",
    ],
)
def test_live_session_guard_malformed_result_blocks_before_submit(result) -> None:
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        session_guard=_ScriptedSessionGuard(result),
        market_policy=_india_policy_with_core_session_guard(),
    )

    execution = orchestrator.execute(_live_request(), broker=broker)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert execution.reason == "live session guard returned an invalid result"
    assert gate.allow_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.check_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


def test_live_session_guard_denial_preserves_reason() -> None:
    reason = "trading session is closed for test"
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        session_guard=_ScriptedSessionGuard(SessionGuardResult(False, reason)),
        market_policy=_india_policy_with_core_session_guard(),
    )

    execution = orchestrator.execute(_live_request(), broker=broker)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert execution.reason == reason
    assert gate.allow_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.check_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


def test_live_trading_gate_malformed_allow_blocks_before_reservation() -> None:
    gate = _ScriptedGate(allow_result=1)
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        trading_gate=gate,
    )

    execution = orchestrator.execute(_live_request(), broker=broker)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert execution.reason == "live trading gate returned an invalid result"
    assert gate.allow_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.check_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


def test_transactional_live_gate_malformed_permit_blocks_before_reservation() -> None:
    gate = _ScriptedGate(permit_result="true")
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        trading_gate=gate,
    )
    request = _live_request()

    execution = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert execution.reason == "live trading gate returned an invalid result"
    assert gate.allow_calls == 0
    assert gate.permit_calls == 1
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0


def test_transactional_live_gate_malformed_admission_blocks_before_submit() -> None:
    gate = _ScriptedGate(admit_result=object())
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        trading_gate=gate,
    )
    request = _live_request()

    execution = _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert execution.reason == "live trading gate returned an invalid result"
    assert gate.allow_calls == 0
    assert gate.permit_calls == 1
    assert gate.admit_calls == 1
    assert store.reserve_calls == 1
    assert broker.submit_calls == 0
    assert unit_of_work.committed is True


def test_live_valid_session_guard_and_gate_proceed() -> None:
    gate = _ScriptedGate()
    orchestrator, gate, store, broker, unit_of_work = _live_callback_orchestrator(
        session_guard=_ScriptedSessionGuard(SessionGuardResult(True)),
        trading_gate=gate,
        market_policy=_india_policy_with_core_session_guard(),
    )

    execution = orchestrator.execute(_live_request(), broker=broker)

    assert execution.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in execution.reason
    assert gate.allow_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


def test_live_risk_rejection_blocks_without_broker_submit() -> None:
    store = _CountingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    broker = FakeBroker()

    def reject(request) -> RiskResult:
        return RiskResult(RiskDecision.REJECT, "test risk rejected")

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=reject,
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert store.reserve_calls == 0
    assert broker.submit_calls == 0


def test_live_with_approving_risk_evaluator_proceeds() -> None:
    broker = FakeBroker()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    ).execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert broker.submit_calls == 0


def test_paper_execution_does_not_require_live_risk_evaluator() -> None:
    orchestrator = ExecutionOrchestrator(
        paper_executor=FakePaperExecutor(),
        policy_verifier=policy_verifier(),
    )
    request = _request(ExecutionMode.PAPER)
    snapshot = Quote(
        instrument=request.order.instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )

    result = orchestrator.execute(request, snapshot=snapshot)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None


def test_live_unresolved_product_blocks_before_gate_reservation_and_broker() -> None:
    """The LIVE unresolved-product guard is a real control-path regression.

    It must run before gate acquisition, any durable idempotency reservation,
    and any broker probe or submission.
    """
    store = _CountingIdempotencyStore()
    unit_of_work = _FakeUnitOfWork(store)
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    broker = FakeBroker(connection_id=BrokerConnectionId("conn-1"))
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_instrument().market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        required_capabilities=frozenset({BrokerCapability.ORDER_SUBMISSION}),
        execution_context=context,
        position_effect=PositionEffect.OPEN,
    )
    # A request that never resolved a product: the explicit effect keeps the
    # request constructible without a product proof, so the LIVE guard is
    # what blocks it.
    request = ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        position_effect=PositionEffect.OPEN,
    )

    result = ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=gate,
        application_runtime=_started_runtime(),
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "resolved product" in result.reason
    assert gate.allow_calls == 0
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0
    assert store.check_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.committed is False


def test_orchestrator_does_not_resolve_products_at_submission_time() -> None:
    """The dispatcher consumes approved semantics; it never resolves them."""
    with pytest.raises(TypeError):
        ExecutionOrchestrator(
            paper_executor=FakePaperExecutor(),
            product_selection=INDIA_EQUITY_PRODUCT_SELECTION,  # type: ignore[call-arg]
            policy_verifier=policy_verifier(),
        )


@pytest.mark.parametrize("declared", ["false", 1, None])
def test_live_gate_durability_non_boolean_declaration_is_blocked(
    declared: object,
) -> None:
    gate = _GateReportingDurability(declared)
    orchestrator, store, broker = _live_prerequisite_orchestrator(
        gate=gate,
        runtime=_started_runtime(),
    )

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == ("live execution requires a boolean durable TradingGate declaration")
    _assert_no_live_prerequisite_side_effects(gate, store, broker)


def test_live_gate_durability_false_keeps_existing_reason() -> None:
    gate = _GateReportingDurability(False)
    orchestrator, store, broker = _live_prerequisite_orchestrator(
        gate=gate,
        runtime=_started_runtime(),
    )

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "live execution requires a durable TradingGate"
    _assert_no_live_prerequisite_side_effects(gate, store, broker)


@pytest.mark.parametrize("declared", ["false", 1, None])
def test_live_runtime_started_non_boolean_declaration_is_blocked(
    declared: object,
) -> None:
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    orchestrator, store, broker = _live_prerequisite_orchestrator(
        gate=gate,
        runtime=_runtime_reporting(declared),
    )

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == (
        "live execution requires a boolean started ApplicationRuntime declaration"
    )
    _assert_no_live_prerequisite_side_effects(gate, store, broker)


def test_live_runtime_started_false_keeps_existing_reason() -> None:
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    orchestrator, store, broker = _live_prerequisite_orchestrator(
        gate=gate,
        runtime=_runtime_reporting(False),
    )

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "live execution requires a started ApplicationRuntime"
    _assert_no_live_prerequisite_side_effects(gate, store, broker)


def test_live_exact_true_prerequisites_proceed() -> None:
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    orchestrator, store, broker = _live_prerequisite_orchestrator(
        gate=gate,
        runtime=_started_runtime(),
    )

    result = orchestrator.execute(_live_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "application-owned risk evaluator" in result.reason
    assert broker.submit_calls == 0
    assert gate.allow_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert store.reserve_calls == 0


# The orchestrator validates the idempotency decision returned by ``check()`` and
# by ``reserve_or_get()`` against the request it is dispatching. The doubles below
# run the real store logic and then return a decision the store can never produce,
# so each test proves the fail-closed outcome: BLOCKED with a fixed reason, before
# submit admission, with no broker call and the reservation transaction rolled
# back rather than committed.
_LIVE_DECISION_REJECTED_REASON = (
    "live idempotency decision failed contract validation; no broker submission was attempted"
)


class _CorruptingIdempotencyStore(_CountingIdempotencyStore):
    """Counting in-memory store that can return a decision it never produced.

    ``check``/``reserve_or_get`` still run the real store logic, so the
    reservation is genuinely created before the corrupted decision is returned.
    """

    def __init__(self, *, check_corruption=None, reserve_corruption=None) -> None:
        super().__init__()
        self._check_corruption = check_corruption
        self._reserve_corruption = reserve_corruption

    def check(self, client_order_id, request_fingerprint):
        decision = super().check(client_order_id, request_fingerprint)
        if self._check_corruption is None:
            return decision
        return self._check_corruption(decision)

    def reserve_or_get(self, client_order_id, request_fingerprint, pending_context=None):
        decision = super().reserve_or_get(client_order_id, request_fingerprint, pending_context)
        if self._reserve_corruption is None:
            return decision
        return self._reserve_corruption(decision)


class _ScopeRecordingUnitOfWork(_FakeUnitOfWork):
    """Fake unit of work that records the outcome of every transaction scope.

    The LIVE flow opens a read-only pre-check scope before the reservation
    scope, so a cumulative flag cannot say which one rolled back. The flags are
    reset on entry and each outcome is appended, which keeps the reservation
    scope's own fate visible.
    """

    def __init__(self, store=None) -> None:
        super().__init__(store)
        self.outcomes: list[str] = []

    def __enter__(self):
        self.committed = False
        self.rolled_back = False
        return super().__enter__()

    def commit(self) -> None:
        super().commit()
        self.outcomes.append("commit")

    def rollback(self) -> None:
        super().rollback()
        self.outcomes.append("rollback")


def _live_decision_orchestrator(store):
    unit_of_work = _ScopeRecordingUnitOfWork(store)
    gate = _CountingGate(InMemoryTradingGateStateStore(), default_enabled=True)
    broker = FakeBroker(connection_id=BrokerConnectionId("conn-1"))
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=unit_of_work,
        trading_gate=gate,
        submission_quarantine=_FakeSubmissionQuarantine(),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        policy_verifier=policy_verifier(),
    )
    return orchestrator, gate, broker, unit_of_work


def test_check_decision_with_receipt_on_a_pending_reservation_is_blocked() -> None:
    """A receipt on a pending reservation is a state no reservation store produces."""
    store = _CorruptingIdempotencyStore(
        check_corruption=lambda decision: replace(
            decision,
            existing_receipt_id=uuid4(),
            reservation_pending=True,
        )
    )
    orchestrator, gate, broker, unit_of_work = _live_decision_orchestrator(store)
    request = _live_request()

    with pytest.raises(IdempotencyDecisionValidationError):
        _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert store.check_calls == 1
    assert store.reserve_calls == 0
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.outcomes == ["rollback"]
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


def test_check_decision_with_a_foreign_identity_is_blocked() -> None:
    """A decision about another client order is evidence about another order."""
    store = _CorruptingIdempotencyStore(
        check_corruption=lambda decision: replace(decision, client_order_id=uuid4())
    )
    orchestrator, gate, broker, unit_of_work = _live_decision_orchestrator(store)
    request = _live_request()

    with pytest.raises(IdempotencyDecisionValidationError):
        _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert store.check_calls == 1
    assert gate.permit_calls == 0
    assert gate.admit_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.outcomes == ["rollback"]
    assert unit_of_work.rolled_back is True


def test_reserve_decision_acquired_without_pending_is_blocked_and_rolled_back() -> None:
    """An acquired reservation that is not pending never reaches submit admission.

    The permit is already held at this site by construction (the reservation
    happens inside ``submission_permit()``), so the provable property is
    rejection before submit admission, before any broker call, with the
    reservation transaction rolled back.
    """
    store = _CorruptingIdempotencyStore(
        reserve_corruption=lambda decision: replace(decision, reservation_pending=False)
    )
    orchestrator, gate, broker, unit_of_work = _live_decision_orchestrator(store)
    request = _live_request()

    with pytest.raises(IdempotencyDecisionValidationError):
        _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert store.reserve_calls == 1
    assert gate.permit_calls == 1
    assert gate.admit_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.outcomes == ["commit", "rollback"]
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


def test_reserve_decision_with_receipt_on_a_pending_reservation_is_blocked() -> None:
    """A receipt on a pending reservation never becomes an EXECUTED duplicate."""
    store = _CorruptingIdempotencyStore(
        reserve_corruption=lambda decision: replace(
            decision,
            existing_receipt_id=uuid4(),
            reservation_acquired=False,
        )
    )
    orchestrator, gate, broker, unit_of_work = _live_decision_orchestrator(store)
    request = _live_request()

    with pytest.raises(IdempotencyDecisionValidationError):
        _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
    assert store.reserve_calls == 1
    assert gate.admit_calls == 0
    assert broker.submit_calls == 0
    assert unit_of_work.outcomes == ["commit", "rollback"]
    assert unit_of_work.rolled_back is True


class _CorruptingSqliteIdempotencyStore:
    """Durable store that corrupts the decision after the genuine reservation INSERT."""

    def __init__(self, inner: SqliteIdempotencyStore, corruption) -> None:
        self._inner = inner
        self._corruption = corruption

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def reserve_or_get(self, *args, **kwargs):
        return self._corruption(self._inner.reserve_or_get(*args, **kwargs))


class _RecordingSqliteUnitOfWork(SqliteUnitOfWork):
    """Durable unit of work that records which scope committed and which rolled back.

    ``SqliteUnitOfWork`` delegates the commit/rollback decision to
    ``SqliteDatabase.transaction``, so that branch is mirrored here for evidence
    and then delegated unchanged. ``committed``/``rolled_back`` describe the most
    recent scope because the LIVE flow opens a read-only pre-check scope first.
    """

    def __init__(self, database: SqliteDatabase, corruption) -> None:
        super().__init__(database)
        self._corrupting = _CorruptingSqliteIdempotencyStore(
            super().idempotency,
            corruption,
        )
        self.committed = False
        self.rolled_back = False
        self.outcomes: list[str] = []

    @property
    def idempotency(self):
        return self._corrupting

    def __enter__(self):
        self.committed = False
        self.rolled_back = False
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.committed = True
            self.outcomes.append("commit")
        else:
            self.rolled_back = True
            self.outcomes.append("rollback")
        super().__exit__(exc_type, exc_value, traceback)


def test_malformed_reserve_decision_rolls_back_and_leaves_no_pending_row(tmp_path) -> None:
    """A rejected reservation decision leaves no durable trace of its own transaction.

    The PENDING row is genuinely inserted before the corrupted decision is
    returned, so only a rollback can explain its absence afterwards. The
    submission is rejected before submit admission with no broker call, and the
    connection is not left holding the failed transaction.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        reserved: list[IdempotencyDecision] = []

        def corrupt(decision):
            reserved.append(decision)
            return replace(decision, reservation_pending=False)

        unit_of_work = _RecordingSqliteUnitOfWork(database, corrupt)
        gate = _CountingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        broker = FakeBroker(connection_id=BrokerConnectionId("conn-1"))
        orchestrator = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=unit_of_work,
            trading_gate=gate,
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=_approving_live_risk_evaluator(),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            policy_verifier=policy_verifier(),
        )
        request = _live_request()

        with pytest.raises(IdempotencyDecisionValidationError):
            _execute_admitted_transaction(orchestrator, request, broker, unit_of_work)
        assert gate.admit_calls == 0
        assert broker.submit_calls == 0
        assert unit_of_work.outcomes == ["commit", "rollback"]
        assert unit_of_work.committed is False
        assert unit_of_work.rolled_back is True
        # The durable store reports acquisition only after it really inserted, so
        # this is the proof that the absent row was inserted and then rolled back.
        assert len(reserved) == 1
        assert reserved[0].reservation_pending is True
        assert reserved[0].reservation_acquired is True
        assert reserved[0].pending_context is not None
        connection = database.connection()
        assert connection.in_transaction is False
        remaining = connection.execute(
            "SELECT COUNT(*) FROM idempotency_reservations WHERE client_order_id = ?",
            (str(request.order.client_order_id),),
        ).fetchone()
        assert remaining[0] == 0
    finally:
        database.close()
