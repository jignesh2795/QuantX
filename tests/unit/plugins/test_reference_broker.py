from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.brokers import BrokerConnectionRef, BrokerCapability
from quantx.plugins.reference_broker import (
    InMemoryReferenceBrokerTransport,
    ReferenceBrokerAdapter,
)
from quantx.ports.broker import BrokerPort


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
        quantity=Decimal("2"),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(transport=None, instrument=None) -> ReferenceBrokerAdapter:
    instrument = instrument or _instrument()
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "reference",
        "NSE",
    )
    return ReferenceBrokerAdapter(
        _connection=connection,
        _instruments=(instrument,),
        _transport=transport or InMemoryReferenceBrokerTransport(fill_price=Decimal("100")),
    )


def test_reference_adapter_is_a_runtime_broker_port() -> None:
    adapter = _adapter()

    assert isinstance(adapter, BrokerPort)
    assert adapter.descriptor.broker_id == "reference"
    assert adapter.capabilities().supports(BrokerCapability.ORDER_SUBMISSION)


def test_reference_adapter_translates_and_normalizes_filled_response() -> None:
    transport = InMemoryReferenceBrokerTransport(fill_price=Decimal("100"))
    adapter = _adapter(transport)
    receipt = adapter.submit(_request())

    assert isinstance(receipt, ExecutionReceipt)
    assert receipt.outcome is ExecutionOutcome.FILLED
    assert receipt.order_status is OrderStatus.FILLED
    assert receipt.simulated is True
    assert receipt.source == "reference-broker"
    assert receipt.fills[0].price == Decimal("100")
    assert receipt.fills[0].quantity == Decimal("2")
    assert transport.requests[0].symbol == "TCS"
    assert transport.requests[0].side == "BUY"
    assert transport.requests[0].order_type == "MARKET"


def test_reference_transport_is_deterministic_for_same_request() -> None:
    transport = InMemoryReferenceBrokerTransport(fill_price=Decimal("100"))
    adapter = _adapter(transport)
    first = adapter.submit(_request())
    second = adapter.submit(_request())

    assert first.executed_at == second.executed_at
    assert first.broker_order_id == second.broker_order_id


def test_reference_adapter_maps_rejection_without_inventing_a_fill() -> None:
    adapter = _adapter(InMemoryReferenceBrokerTransport(accepted=False))
    receipt = adapter.submit(_request())

    assert receipt.outcome is ExecutionOutcome.REJECTED
    assert receipt.order_status is OrderStatus.REJECTED
    assert receipt.fills == ()


def test_reference_adapter_rejects_market_mismatch() -> None:
    wrong_market = replace(
        _instrument(),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"),
    )
    adapter = _adapter(instrument=wrong_market)

    with pytest.raises(ValueError, match="market"):
        adapter.submit(_request())


def test_reference_adapter_emits_domain_receipt_not_transport_response() -> None:
    transport = InMemoryReferenceBrokerTransport(fill_price=Decimal("100"))
    adapter = _adapter(transport)
    receipt = adapter.submit(_request())

    assert type(receipt).__name__ == "ExecutionReceipt"
    assert all(type(fill).__name__ == "Fill" for fill in receipt.fills)
    assert not hasattr(receipt, "outcome_code")
