from dataclasses import replace
from decimal import Decimal

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
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
from quantx.execution.receipts.models import (
    ExecutionOutcome,
    ExecutionReceipt,
)
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.plugins.dhan import (
    DhanBrokerAdapter,
    DhanInstrumentRef,
    InMemoryDhanTransport,
)
from quantx.plugins.dhan.mapping import dhan_correlation_id


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _request(
    *,
    mode: ExecutionMode = ExecutionMode.LIVE,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.DAY,
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=order_type,
        time_in_force=time_in_force,
        limit_price=Decimal("100") if order_type is OrderType.LIMIT else None,
        stop_price=Decimal("99") if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} else None,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(transport: InMemoryDhanTransport | None = None) -> DhanBrokerAdapter:
    instrument = _instrument()
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        "NSE_EQ",
    )
    return DhanBrokerAdapter(
        _connection=connection,
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
    )


def test_submit_translates_to_dhan_and_returns_normalized_receipt() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    request = _request()
    receipt = _adapter(transport).submit(request)

    assert isinstance(receipt, ExecutionReceipt)
    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert receipt.order_status is OrderStatus.ACCEPTED
    assert receipt.source == "dhan"
    assert receipt.simulated is False
    assert receipt.broker_order_id == "dhan-test-order"
    assert receipt.correlation_id == request.correlation_id
    assert transport.submitted[0].security_id == "1333"
    assert transport.submitted[0].exchange_segment == "NSE_EQ"
    assert transport.submitted[0].product_type == "CNC"
    assert transport.submitted[0].correlation_id == dhan_correlation_id(request.correlation_id)


def test_submit_rejects_wrong_account_for_bound_connection() -> None:
    request = _request()
    wrong_context = replace(
        request.execution_context,
        account_id=AccountId("other-account"),
    )
    wrong_request = replace(request, execution_context=wrong_context)

    with pytest.raises(ValueError, match="account"):
        _adapter().submit(wrong_request)


def test_submit_rejects_wrong_connection_for_bound_connection() -> None:
    request = _request()
    wrong_context = replace(
        request.execution_context,
        broker_connection_id=BrokerConnectionId("other-connection"),
    )
    wrong_request = replace(request, execution_context=wrong_context)

    with pytest.raises(ValueError, match="connection"):
        _adapter().submit(wrong_request)


def test_submit_rejects_unsupported_dhan_validity_before_transport() -> None:
    transport = InMemoryDhanTransport()
    request = _request(time_in_force=TimeInForce.GTC)

    with pytest.raises(ValueError, match="DAY/IOC"):
        _adapter(transport).submit(request)

    assert transport.submitted == ()


def test_reconcile_rejects_mismatched_broker_correlation_id() -> None:
    class MismatchedCorrelationTransport(InMemoryDhanTransport):
        def reconcile(self, correlation_id):  # type: ignore[no-untyped-def]
            detail = super().reconcile(correlation_id)
            return replace(detail, correlation_id="some-other-correlation")

    receipt = _adapter(
        MismatchedCorrelationTransport(
            response_status="TRADED",
            filled_quantity=Decimal("2"),
            average_traded_price=Decimal("101"),
        )
    ).reconcile(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN
    assert "mismatched correlation" in receipt.message


def test_reconcile_rejects_fill_above_canonical_order_quantity() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("3"),
        average_traded_price=Decimal("101"),
    )

    with pytest.raises(ValueError, match="exceeds canonical order quantity"):
        _adapter(transport).reconcile(_request())


def test_reconcile_rejects_filled_quantity_without_price() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=None,
    )

    with pytest.raises(ValueError, match="requires an average traded price"):
        _adapter(transport).reconcile(_request())


def test_reconcile_maps_trade_and_uses_broker_reported_fill() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("101.25"),
    )
    request = _request()
    receipt = _adapter(transport).reconcile(request)

    assert receipt.outcome is ExecutionOutcome.FILLED
    assert receipt.order_status is OrderStatus.FILLED
    assert len(receipt.fills) == 1
    assert receipt.fills[0].quantity == Decimal("2")
    assert receipt.fills[0].price == Decimal("101.25")


def test_reconcile_preserves_partial_trade_status() -> None:
    transport = InMemoryDhanTransport(
        response_status="PART_TRADED",
        filled_quantity=Decimal("1"),
        average_traded_price=Decimal("101"),
    )
    receipt = _adapter(transport).reconcile(_request())

    assert receipt.outcome is ExecutionOutcome.PARTIALLY_FILLED
    assert receipt.order_status is OrderStatus.PARTIALLY_FILLED
    assert receipt.fills[0].quantity == Decimal("1")


def test_cancel_uses_dhan_safe_correlation_identifier() -> None:
    transport = InMemoryDhanTransport()
    request = _request()
    receipt = _adapter(transport).cancel(request)

    assert receipt.outcome is ExecutionOutcome.CANCELLED
    assert transport.cancelled == (dhan_correlation_id(request.correlation_id),)


def test_unknown_transport_failure_fails_closed() -> None:
    class FailingTransport(InMemoryDhanTransport):
        def submit(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("network unavailable")

    receipt = _adapter(FailingTransport()).submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN
    assert "network unavailable" in receipt.message


def test_unknown_broker_status_maps_to_unknown() -> None:
    receipt = _adapter(InMemoryDhanTransport(response_status="NEW_STATUS")).submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN


def test_market_segment_mismatch_is_rejected() -> None:
    instrument = _instrument()
    wrong = replace(
        instrument,
        market=MarketContext(
            MarketRegion.INDIA,
            MarketFamily.EQUITY,
            "BSE",
            "IN",
        ),
    )
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        "BSE_EQ",
    )
    adapter = DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            wrong.instrument_id: (
                wrong,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                    product_type="CNC",
                ),
            )
        },
        _transport=InMemoryDhanTransport(),
    )

    with pytest.raises(ValueError, match="market venue"):
        adapter.submit(_request())


def test_dhan_adapter_composes_with_live_execution_orchestrator() -> None:
    adapter = _adapter(InMemoryDhanTransport(response_status="PENDING"))
    result = ExecutionOrchestrator().execute(_request(), broker=adapter)

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.source == "dhan"


def test_account_state_produces_canonical_broker_observation() -> None:
    from quantx.integrations.reconciliation import StateSource

    transport = InMemoryDhanTransport(
        funds_available_balance=Decimal("5000"),
        funds_utilized_amount=Decimal("1200"),
    )
    state = _adapter(transport).account_state()

    assert state.account_id == AccountId("acct-1")
    assert state.connection_id == BrokerConnectionId("conn-1")
    assert state.source is StateSource.BROKER
    assert state.currency == "INR"
    assert state.available_cash == Decimal("5000")
    assert state.margin_used == Decimal("1200")
    assert state.equity is None
    assert state.margin_available is None


def test_account_state_missing_funds_remain_none_not_zero() -> None:
    transport = InMemoryDhanTransport(
        funds_available_balance=None,
        funds_utilized_amount=None,
    )
    state = _adapter(transport).account_state()

    assert state.available_cash is None
    assert state.margin_used is None


def test_position_states_map_known_broker_instruments() -> None:
    from quantx.integrations.reconciliation import StateSource
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        position_snapshots=(DhanPositionSnapshot("1333", "NSE_EQ", Decimal("10"), Decimal("100")),)
    )
    states = _adapter(transport).position_states()

    assert len(states) == 1
    assert states[0].account_id == AccountId("acct-1")
    assert states[0].connection_id == BrokerConnectionId("conn-1")
    assert states[0].instrument_id == "NSE:TCS"
    assert states[0].quantity == Decimal("10")
    assert states[0].average_price == Decimal("100")
    assert states[0].source is StateSource.BROKER


def test_position_states_with_unmapped_broker_position_fails_closed() -> None:
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        position_snapshots=(DhanPositionSnapshot("9999", "BSE_EQ", Decimal("5"), None),)
    )

    with pytest.raises(ValueError, match="no canonical instrument mapping"):
        _adapter(transport).position_states()


def test_position_states_with_unavailable_observation_fails_closed() -> None:
    transport = InMemoryDhanTransport(
        positions_available=False,
        positions_message="network unavailable",
    )

    with pytest.raises(ValueError, match="unavailable"):
        _adapter(transport).position_states()
