from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.integrations.brokers import BrokerCapability, BrokerConnectionRef
from quantx.plugins.dhan import (
    DhanBrokerAdapter,
    DhanInstrumentRef,
    InMemoryDhanTransport,
)
from quantx.ports.broker import BrokerPort


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
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def test_dhan_adapter_conforms_to_broker_port() -> None:
    adapter = _adapter()

    assert isinstance(adapter, BrokerPort)
    assert adapter.descriptor.broker_id == "dhan"
    assert adapter.descriptor.display_name == "Dhan"
    assert adapter.connection.broker_id == "dhan"
    assert adapter.capabilities().supports(BrokerCapability.ORDER_SUBMISSION)


def test_dhan_plugin_descriptor_exposes_only_implemented_capabilities() -> None:
    from quantx.plugins.dhan import DHAN_CAPABILITIES, DHAN_PLUGIN_DESCRIPTOR

    assert set(DHAN_PLUGIN_DESCRIPTOR.capabilities) == {
        capability.value for capability in DHAN_CAPABILITIES.values
    }
    assert BrokerCapability.POSITIONS in DHAN_CAPABILITIES.values
    assert BrokerCapability.BALANCES in DHAN_CAPABILITIES.values
    assert BrokerCapability.ORDER_SUBMISSION in DHAN_CAPABILITIES.values
    assert BrokerCapability.ORDER_CANCELLATION in DHAN_CAPABILITIES.values


def test_only_dhan_transport_contains_vendor_sdk_import() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "src" / "quantx"
    allowed = root / "plugins" / "dhan" / "transport.py"
    forbidden = []
    for path in root.rglob("*.py"):
        if "dhanhq" in path.read_text(encoding="utf-8") and path != allowed:
            forbidden.append(str(path))
    assert forbidden == []


def test_dhan_registration_hook() -> None:
    from quantx.plugins import PluginRegistry
    from quantx.plugins.dhan import DHAN_PLUGIN_DESCRIPTOR, register_dhan_broker

    registry = PluginRegistry()
    register_dhan_broker(registry, lambda: object())

    registration = registry.get(DHAN_PLUGIN_DESCRIPTOR.plugin_id)
    assert registration.descriptor.name == "Dhan"


def test_dhan_credentials_do_not_expose_access_token_in_repr() -> None:
    from quantx.plugins.dhan import DhanCredentials

    credentials = DhanCredentials("1000000001", "secret-token")
    rendered = repr(credentials)

    assert "1000000001" in rendered
    assert "secret-token" not in rendered
