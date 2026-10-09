from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread
from uuid import uuid4

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
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.trading_gate import (
    DurableTradingGate,
    InMemoryTradingGateStateStore,
    TradingGate,
)
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
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
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)


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
    context = ExecutionContext(
        account_id=account_id or AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=connection_id,
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
        required_capabilities=required_capabilities,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
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


class _FakeUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self._store = InMemoryIdempotencyStore()
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
    return DurableTradingGate(InMemoryTradingGateStateStore())


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


def test_paper_requires_an_observed_snapshot() -> None:
    orchestrator = ExecutionOrchestrator(paper_executor=FakePaperExecutor())
    result = orchestrator.execute(_request(ExecutionMode.PAPER))
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "snapshot" in result.reason


def test_paper_rejects_snapshot_for_wrong_instrument() -> None:
    orchestrator = ExecutionOrchestrator(paper_executor=FakePaperExecutor())
    wrong = Quote(
        instrument=InstrumentId("NSE", "INFY"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )
    result = orchestrator.execute(_request(ExecutionMode.PAPER), snapshot=wrong)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "instrument" in result.reason


def test_paper_executes_with_matching_snapshot() -> None:
    orchestrator = ExecutionOrchestrator(paper_executor=FakePaperExecutor())
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    ).execute(
        request,
        broker=FakeBroker(),
    )
    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.source == "fake-broker"


def test_live_submission_is_idempotent_through_canonical_boundary() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    first = orchestrator.execute(request, broker=broker)
    second = orchestrator.execute(request, broker=broker)

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
    broker = FailingBroker()
    orchestrator = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=_durable_gate(),
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    result = orchestrator.execute(request, broker=broker)

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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    first = orchestrator.execute(request, broker=broker)

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

    second = orchestrator.execute(request, broker=broker)

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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    result = orchestrator.execute(request, broker=broker)

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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    result = orchestrator.execute(request, broker=broker)

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

    result = ExecutionOrchestrator(unit_of_work=unit_of_work).execute(
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
        application_runtime=runtime,
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
        application_runtime=_started_runtime(),
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    def run_execution() -> None:
        outcome["result"] = orchestrator.execute(request, broker=broker)

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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    ).execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "durable UnitOfWork" in result.reason
    assert broker.submit_calls == 0


def test_live_rejects_process_local_trading_gate() -> None:
    request = _live_request()
    broker = FakeBroker()
    gate = TradingGate()

    result = ExecutionOrchestrator(
        application_runtime=_started_runtime(),
        unit_of_work=_FakeUnitOfWork(),
        trading_gate=gate,
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )

    first = orchestrator.execute(request, broker=broker)
    assert first.status is ExecutionDispatchStatus.EXECUTED
    assert first.receipt is not None

    second = orchestrator.execute(request, broker=broker)
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
        trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
    )
    return database, unit_of_work, orchestrator


def test_sqlite_first_execution_persists_receipt_and_completion(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()
        result = orchestrator.execute(request, broker=broker)
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
        first = orchestrator.execute(request, broker=broker)
        assert first.status is ExecutionDispatchStatus.EXECUTED
        second = orchestrator.execute(request, broker=broker)
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
        result = orchestrator.execute(request, broker=broker)
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None
        assert "reconciliation" in result.reason
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
        second = orchestrator.execute(request, broker=broker)
        assert second.status is ExecutionDispatchStatus.UNKNOWN
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_fingerprint_mismatch_rejected_without_submit(tmp_path) -> None:
    database, unit_of_work, orchestrator = _sqlite_setup(tmp_path)
    try:
        request = _live_request()
        broker = FakeBroker()
        first = orchestrator.execute(request, broker=broker)
        assert first.status is ExecutionDispatchStatus.EXECUTED
        changed_order = replace(request.order, quantity=Decimal("11"))
        changed_request = replace(request, order=changed_order)
        with pytest.raises(ValueError, match="different request"):
            orchestrator.execute(changed_request, broker=broker)
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_sqlite_complete_survives_restart_proxy(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    request = _live_request()
    database_a = SqliteDatabase(path)
    try:
        orchestrator_a = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=SqliteUnitOfWork(database_a),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database_a)),
            india_rule_evaluator=_approving_india_evaluator(),
            india_session_evaluator=_approving_india_session_evaluator(),
        )
        first = orchestrator_a.execute(request, broker=FakeBroker())
        assert first.status is ExecutionDispatchStatus.EXECUTED
    finally:
        database_a.close()
    database_b = SqliteDatabase(path)
    try:
        broker_b = FakeBroker()
        orchestrator_b = ExecutionOrchestrator(
            application_runtime=_started_runtime(),
            unit_of_work=SqliteUnitOfWork(database_b),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database_b)),
            india_rule_evaluator=_approving_india_evaluator(),
            india_session_evaluator=_approving_india_session_evaluator(),
        )
        second = orchestrator_b.execute(request, broker=broker_b)
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
        result = orchestrator.execute(request, broker=broker)
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
        second = orchestrator.execute(request, broker=broker)
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
        india_rule_evaluator=_approving_india_evaluator(),
        india_session_evaluator=_approving_india_session_evaluator(),
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

        result = orchestrator.execute(_live_request(), broker=InspectingBroker())
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
    result = ExecutionOrchestrator(paper_executor=adapter).continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=snapshot,
    )

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert adapter.called
