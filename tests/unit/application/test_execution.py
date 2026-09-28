from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
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
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
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
    result = ExecutionOrchestrator().execute(request)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "broker adapter" in result.reason


def test_live_blocks_account_mismatch() -> None:
    request = _request(
        ExecutionMode.LIVE,
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker(account_id=AccountId("acct-2"))
    result = ExecutionOrchestrator().execute(request, broker=broker)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "account" in result.reason


def test_live_blocks_connection_mismatch() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker(connection_id=BrokerConnectionId("conn-2"))
    result = ExecutionOrchestrator().execute(request, broker=broker)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "connection" in result.reason


def test_live_blocks_unhealthy_broker() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    result = ExecutionOrchestrator().execute(
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
    result = ExecutionOrchestrator().execute(request, broker=FakeBroker())
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
    result = ExecutionOrchestrator().execute(
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
    result = ExecutionOrchestrator().execute(request, broker=FakeBroker())
    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.source == "fake-broker"


def test_live_submission_is_idempotent_through_canonical_boundary() -> None:
    request = _request(
        ExecutionMode.LIVE,
        connection_id=BrokerConnectionId("conn-1"),
    )
    broker = FakeBroker()
    orchestrator = ExecutionOrchestrator()

    first = orchestrator.execute(request, broker=broker)
    second = orchestrator.execute(request, broker=broker)

    assert first.status is ExecutionDispatchStatus.EXECUTED
    assert first.receipt is not None
    assert second.status is ExecutionDispatchStatus.EXECUTED
    assert second.receipt is None
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
    orchestrator = ExecutionOrchestrator()

    result = orchestrator.execute(request, broker=broker)

    assert result.status is ExecutionDispatchStatus.UNKNOWN
    assert result.receipt is None
    assert "reconciliation" in result.reason
    assert broker.submit_calls == 1
