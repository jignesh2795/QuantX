from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.ports.broker import BrokerPort
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport


def _request() -> ApprovedExecutionRequest:
    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
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
        quantity=Decimal("1"),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter() -> DhanBrokerAdapter:
    instrument = _request().order.instrument
    full = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
            "dhan",
            "NSE_EQ",
        ),
        _instruments={
            instrument: (
                full,
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=InMemoryDhanTransport(),
    )


def test_dhan_adapter_conforms_to_broker_port() -> None:
    adapter = _adapter()

    assert isinstance(adapter, BrokerPort)
    assert adapter.descriptor.broker_id == "dhan"
    assert adapter.descriptor.display_name == "Dhan"
    assert adapter.connection.broker_id == "dhan"
    assert adapter.capabilities().supports(
        __import__("quantx.integrations.brokers", fromlist=["BrokerCapability"]).BrokerCapability.ORDER_SUBMISSION
    )
