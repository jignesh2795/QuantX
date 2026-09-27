from decimal import Decimal
from uuid import uuid4

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.ports import ExecutionReceipt, ExecutionOutcome
from quantx.ports.broker import BrokerPort
from quantx.integrations.brokers import BrokerCapability, BrokerConnectionRef, BrokerDescriptor, CapabilitySet
from quantx.domain.orders import Fill


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


def _request() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    return ApprovedExecutionRequest(order, context, RiskResult(RiskDecision.APPROVE, "approved"))


class ReferenceBroker:
    def __init__(self, instrument: Instrument) -> None:
        self._instrument = instrument
        self._connection = BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
            "reference",
            "NSE",
        )
        self._capabilities = CapabilitySet(
            frozenset({BrokerCapability.ORDER_SUBMISSION, BrokerCapability.MARKET_DATA})
        )
        self.descriptor = BrokerDescriptor("reference", "Reference Broker", self._capabilities, "1.0")

    @property
    def connection(self) -> BrokerConnectionRef:
        return self._connection

    def health(self) -> bool:
        return True

    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def instrument(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instrument if instrument_id == self._instrument.instrument_id else None

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        now = request.order.created_at
        fill = Fill(
            client_order_id=request.order.client_order_id,
            instrument=request.order.instrument,
            side=request.order.side,
            quantity=request.order.quantity,
            price=Decimal("100"),
            filled_at=now,
        )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=now,
            fills=(fill,),
            simulated=False,
            source="reference-broker",
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self.submit(request)

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self.submit(request)


def test_reference_broker_conforms_to_broker_port_behavior() -> None:
    instrument = _instrument()
    adapter: BrokerPort = ReferenceBroker(instrument)

    assert adapter.health()
    assert adapter.connection == adapter._connection
    assert adapter.capabilities().supports(BrokerCapability.ORDER_SUBMISSION)
    assert adapter.instrument(instrument.instrument_id) == instrument

    receipt = adapter.submit(_request())
    assert receipt.source == "reference-broker"
    assert receipt.account_id == AccountId("acct-1")
    assert receipt.connection_id == BrokerConnectionId("conn-1")
    assert receipt.outcome is ExecutionOutcome.FILLED
