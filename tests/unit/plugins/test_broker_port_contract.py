"""Shared BrokerPort contract coverage for first-party adapter implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
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
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.ports.broker import BrokerPort
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from quantx.plugins.reference_broker import (
    InMemoryReferenceBrokerTransport,
    ReferenceBrokerAdapter,
)


@dataclass(frozen=True, slots=True)
class _BrokerContractCase:
    name: str
    factory: Callable[[], BrokerPort]


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
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _reference_adapter() -> BrokerPort:
    return ReferenceBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
            "reference",
            "NSE",
        ),
        _instruments=(_instrument(),),
        _transport=InMemoryReferenceBrokerTransport(),
    )


def _dhan_adapter() -> BrokerPort:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
            "dhan",
            "NSE_EQ",
        ),
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                    product_type="CNC",
                ),
            )
        },
        _transport=InMemoryDhanTransport(response_status="PENDING"),
    )


CASES = (
    _BrokerContractCase("reference", _reference_adapter),
    _BrokerContractCase("dhan", _dhan_adapter),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_adapter_satisfies_broker_port_contract(case: _BrokerContractCase) -> None:
    adapter = case.factory()

    assert isinstance(adapter, BrokerPort)
    assert adapter.connection.account_id == AccountId("acct-1")
    assert adapter.connection.connection_id == BrokerConnectionId("conn-1")
    assert adapter.descriptor.broker_id == adapter.connection.broker_id
    assert adapter.descriptor.capabilities == adapter.capabilities()
    assert adapter.descriptor.adapter_version.strip()
    assert isinstance(adapter.health(), bool)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_instrument_lookup_is_identity_scoped(case: _BrokerContractCase) -> None:
    adapter = case.factory()
    known = _instrument().instrument_id
    unknown = InstrumentId("NSE", "INFY")

    assert adapter.instrument(known) == _instrument()
    assert adapter.instrument(unknown) is None


@pytest.mark.parametrize("operation", ("submit", "cancel", "reconcile"))
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_order_operations_return_canonical_receipts(
    case: _BrokerContractCase,
    operation: str,
) -> None:
    adapter = case.factory()
    request = _request()
    receipt = getattr(adapter, operation)(request)

    assert isinstance(receipt, ExecutionReceipt)
    assert receipt.client_order_id == request.order.client_order_id
    assert receipt.account_id == request.execution_context.account_id
    assert receipt.connection_id == request.execution_context.broker_connection_id
    assert receipt.source.strip()
