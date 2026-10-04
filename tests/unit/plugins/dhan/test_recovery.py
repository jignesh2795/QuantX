"""Unit coverage for read-only Dhan recovery evidence."""

from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
    build_order_from_intent,
)
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
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation.broker_evidence import BrokerOrderEvidenceStatus
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.capabilities import DHAN_CAPABILITIES
from quantx.plugins.dhan.models import DhanInstrumentRef, DhanOrderDetail, DhanPositionSnapshot
from quantx.plugins.dhan.recovery import (
    DhanRecoveryEvidenceProvider,
    build_dhan_recovery_provider,
)
from quantx.plugins.dhan.transport import InMemoryDhanTransport


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


def _context(
    account: str = "acct-1",
    connection: str = "conn-1",
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId(account),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_instrument().market,
        broker_connection_id=BrokerConnectionId(connection),
        execution_mode=ExecutionMode.LIVE,
    )


def _recovery_request(
    account: str = "acct-1",
    connection: str = "conn-1",
    quantity: str = "2",
) -> PendingExecutionRecoveryRequest:
    context = _context(account, connection)
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        execution_context=context,
    )
    approved = ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        PolicyResult(PolicyDecision.APPROVE, "approved"),
    )
    return PendingExecutionRecoveryRequest(
        order=approved.order,
        execution_context=context,
        parent_client_order_id=approved.parent_client_order_id,
    )


def _adapter(
    transport: InMemoryDhanTransport | None = None,
    account: str = "acct-1",
    connection: str = "conn-1",
) -> DhanBrokerAdapter:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId(account),
            BrokerConnectionId(connection),
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
        _transport=transport or InMemoryDhanTransport(),
        _capabilities=DHAN_CAPABILITIES,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def _provider(**overrides) -> DhanRecoveryEvidenceProvider:
    request = _recovery_request(
        account=overrides.pop("account", "acct-1"),
        connection=overrides.pop("connection", "conn-1"),
    )
    return build_dhan_recovery_provider(_adapter(**overrides), request)


def test_traded_detail_maps_to_filled_observation() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("100"),
    )
    provider = _provider(transport=transport)

    evidence = provider.fetch_broker_order(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        order_id=provider._order_id,
    )

    assert evidence.status is BrokerOrderEvidenceStatus.FOUND
    observation = evidence.observation
    assert observation is not None
    assert observation.status is OrderLifecycleStatus.FILLED
    assert observation.requested_quantity == "2"
    assert observation.filled_quantity == "2"
    assert observation.broker_order_id == "dhan-test-order"
    assert observation.account_id == AccountId("acct-1")
    assert observation.connection_id == BrokerConnectionId("conn-1")


def test_pending_detail_maps_to_acknowledged_observation() -> None:
    provider = _provider()

    evidence = provider.fetch_broker_order(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        order_id=provider._order_id,
    )

    assert evidence.status is BrokerOrderEvidenceStatus.FOUND
    observation = evidence.observation
    assert observation is not None
    assert observation.status is OrderLifecycleStatus.ACKNOWLEDGED


def test_unknown_broker_status_maps_to_unknown_observation() -> None:
    transport = InMemoryDhanTransport(response_status="SOMETHING_NEW")
    provider = _provider(transport=transport)

    evidence = provider.fetch_broker_order(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        order_id=provider._order_id,
    )

    assert evidence.status is BrokerOrderEvidenceStatus.FOUND
    observation = evidence.observation
    assert observation is not None
    assert observation.status is OrderLifecycleStatus.UNKNOWN


def test_binding_mismatch_rejected_at_construction() -> None:
    request = _recovery_request(account="acct-2")

    with pytest.raises(ValueError, match="account"):
        build_dhan_recovery_provider(_adapter(account="acct-1"), request)


def test_fetch_with_wrong_account_rejected() -> None:
    provider = _provider()

    with pytest.raises(ValueError, match="account"):
        provider.fetch_broker_order(
            account_id=AccountId("acct-2"),
            connection_id=BrokerConnectionId("conn-1"),
            order_id=provider._order_id,
        )


def test_fetch_with_wrong_order_rejected() -> None:
    provider = _provider()

    with pytest.raises(ValueError, match="order"):
        provider.fetch_broker_order(
            account_id=AccountId("acct-1"),
            connection_id=BrokerConnectionId("conn-1"),
            order_id=uuid4(),
        )


def test_mismatched_correlation_rejected() -> None:
    class MismatchedTransport(InMemoryDhanTransport):
        def reconcile(self, correlation_id: str, *, timeout: float):
            detail = super().reconcile(correlation_id, timeout=timeout)
            return DhanOrderDetail(
                order_id=detail.order_id,
                correlation_id="some-other-correlation",
                order_status=detail.order_status,
                average_traded_price=detail.average_traded_price,
                filled_quantity=detail.filled_quantity,
                exchange_time=detail.exchange_time,
                update_time=detail.update_time,
            )

    provider = _provider(transport=MismatchedTransport())

    with pytest.raises(ValueError, match="correlation"):
        provider.fetch_broker_order(
            account_id=AccountId("acct-1"),
            connection_id=BrokerConnectionId("conn-1"),
            order_id=provider._order_id,
        )


def test_transport_failure_surfaces_as_unavailable() -> None:
    class FailingTransport(InMemoryDhanTransport):
        def reconcile(self, correlation_id: str, *, timeout: float):
            raise RuntimeError("broker unreachable")

    provider = _provider(transport=FailingTransport())

    evidence = provider.fetch_broker_order(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        order_id=provider._order_id,
    )

    assert evidence.status is BrokerOrderEvidenceStatus.UNKNOWN
    assert evidence.observation is None


def test_position_selects_bound_instrument() -> None:
    transport = InMemoryDhanTransport(
        position_snapshots=(
            DhanPositionSnapshot(
                security_id="1333",
                exchange_segment="NSE_EQ",
                net_quantity=Decimal("10"),
                average_price=Decimal("100"),
            ),
        )
    )
    provider = _provider(transport=transport)

    state = provider.fetch_broker_position(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        instrument_id="NSE:TCS",
    )

    assert state is not None
    assert state.quantity == Decimal("10")
    assert state.account_id == AccountId("acct-1")
    assert state.connection_id == BrokerConnectionId("conn-1")


def test_position_missing_instrument_returns_none() -> None:
    provider = _provider()

    assert (
        provider.fetch_broker_position(
            account_id=AccountId("acct-1"),
            connection_id=BrokerConnectionId("conn-1"),
            instrument_id="NSE:TCS",
        )
        is None
    )


def test_account_returns_bound_canonical_state() -> None:
    provider = _provider()

    state = provider.fetch_broker_account(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )

    assert state is not None
    assert state.available_cash == Decimal("5000")
    assert state.margin_used == Decimal("1200")
    assert state.account_id == AccountId("acct-1")


def test_provider_exposes_binding_identity() -> None:
    provider = _provider()

    assert isinstance(provider, DhanRecoveryEvidenceProvider)
    assert provider.account_id == AccountId("acct-1")
    assert provider.connection_id == BrokerConnectionId("conn-1")
    assert provider.broker_id == "dhan"
