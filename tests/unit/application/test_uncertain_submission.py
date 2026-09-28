"""Tests for receipt recovery after uncertain submission."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.application.uncertain_submission import UncertainSubmissionReceiptRecovery
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Fill, Order
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import AccountId, BrokerConnectionId, InstrumentId
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.reconciliation.orders import OrderObservation

RECOVERED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _request() -> ApprovedExecutionRequest:
    order = Order(
        instrument=InstrumentId("NSE:TCS"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        time_in_force=TimeInForce.DAY,
        client_order_id=uuid4(),
    )
    return ApprovedExecutionRequest(
        order=order,
        execution_context=ExecutionContext(
            account_id=AccountId("acct-1"),
            portfolio_id=PortfolioId("portfolio-1"),
            deployment_id=StrategyDeploymentId("deployment-1"),
            market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
            broker_connection_id=BrokerConnectionId("conn-1"),
            execution_mode=ExecutionMode.LIVE,
        ),
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _observation(
    request: ApprovedExecutionRequest,
    status: OrderLifecycleStatus,
    *,
    filled: str = "0",
    broker_order_id: str | None = "dhan-1",
) -> OrderObservation:
    return OrderObservation(
        request.order.client_order_id,
        status,
        "2",
        filled,
        broker_order_id,
    )


def _fill(request: ApprovedExecutionRequest, quantity: str = "2") -> Fill:
    return Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal(quantity),
        price=Decimal("100"),
        filled_at=RECOVERED_AT,
    )


def test_acknowledged_order_recovers_accepted_receipt() -> None:
    request = _request()
    receipt = UncertainSubmissionReceiptRecovery().recover(
        request,
        _observation(request, OrderLifecycleStatus.ACKNOWLEDGED),
        request_id=uuid4(),
        recovered_at=RECOVERED_AT,
    )

    assert receipt is not None
    assert receipt.outcome.value == "ACCEPTED"
    assert receipt.order_status is OrderStatus.ACCEPTED
    assert receipt.order_id == request.order.client_order_id
    assert receipt.account_id == AccountId("acct-1")
    assert receipt.connection_id == BrokerConnectionId("conn-1")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (OrderLifecycleStatus.CANCELLED, "CANCELLED"),
        (OrderLifecycleStatus.REJECTED, "REJECTED"),
    ],
)
def test_terminal_non_fill_states_recover_without_fabricating_fills(
    status: OrderLifecycleStatus,
    outcome: str,
) -> None:
    request = _request()
    receipt = UncertainSubmissionReceiptRecovery().recover(
        request,
        _observation(request, status),
        request_id=uuid4(),
        recovered_at=RECOVERED_AT,
    )

    assert receipt is not None
    assert receipt.outcome.value == outcome
    assert receipt.fills == ()


def test_filled_order_requires_real_fill_evidence() -> None:
    request = _request()

    with pytest.raises(ValueError, match="fill quantity"):
        UncertainSubmissionReceiptRecovery().recover(
            request,
            _observation(request, OrderLifecycleStatus.FILLED, filled="2"),
            request_id=uuid4(),
            recovered_at=RECOVERED_AT,
        )


def test_filled_order_reuses_canonical_order_and_real_fill() -> None:
    request = _request()
    fill = _fill(request)
    receipt = UncertainSubmissionReceiptRecovery().recover(
        request,
        _observation(request, OrderLifecycleStatus.FILLED, filled="2"),
        request_id=uuid4(),
        recovered_at=RECOVERED_AT,
        fills=(fill,),
    )

    assert receipt is not None
    assert receipt.outcome.value == "FILLED"
    assert receipt.order_id == request.order.client_order_id
    assert receipt.fills == (fill,)


def test_partial_order_requires_matching_fill_quantity() -> None:
    request = _request()

    with pytest.raises(ValueError, match="fill quantity"):
        UncertainSubmissionReceiptRecovery().recover(
            request,
            _observation(request, OrderLifecycleStatus.PARTIALLY_FILLED, filled="1"),
            request_id=uuid4(),
            recovered_at=RECOVERED_AT,
            fills=(_fill(request, "2"),),
        )


def test_unresolved_lifecycle_status_does_not_create_receipt() -> None:
    request = _request()

    receipt = UncertainSubmissionReceiptRecovery().recover(
        request,
        _observation(request, OrderLifecycleStatus.UNKNOWN),
        request_id=uuid4(),
        recovered_at=RECOVERED_AT,
    )

    assert receipt is None


def test_broker_identity_mismatch_is_rejected() -> None:
    request = _request()
    foreign = OrderObservation(
        uuid4(),
        OrderLifecycleStatus.FILLED,
        "2",
        "2",
        "dhan-1",
    )

    with pytest.raises(ValueError, match="identity"):
        UncertainSubmissionReceiptRecovery().recover(
            request,
            foreign,
            request_id=uuid4(),
            recovered_at=RECOVERED_AT,
            fills=(_fill(request),),
        )


def test_broker_requested_quantity_mismatch_is_rejected() -> None:
    request = _request()
    foreign_quantity = OrderObservation(
        request.order.client_order_id,
        OrderLifecycleStatus.FILLED,
        "3",
        "3",
        "dhan-1",
    )

    with pytest.raises(ValueError, match="requested quantity"):
        UncertainSubmissionReceiptRecovery().recover(
            request,
            foreign_quantity,
            request_id=uuid4(),
            recovered_at=RECOVERED_AT,
            fills=(_fill(request),),
        )
