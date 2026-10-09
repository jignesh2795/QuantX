from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.lifecycle import ExecutionLifecycle


def test_partial_lifecycle_generates_deterministic_continuation_identity() -> None:
    order_id = uuid4()
    lifecycle = ExecutionLifecycle(
        order_id,
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )
    assert lifecycle.continuation_client_order_id(
        Decimal("6")
    ) == lifecycle.continuation_client_order_id(Decimal("6"))


def test_continuation_identity_changes_after_new_fill() -> None:
    order_id = uuid4()
    first = ExecutionLifecycle(order_id, Decimal("10"), Decimal("4"), OrderStatus.PARTIALLY_FILLED)
    second = ExecutionLifecycle(order_id, Decimal("10"), Decimal("7"), OrderStatus.PARTIALLY_FILLED)
    assert first.continuation_client_order_id(Decimal("6")) != second.continuation_client_order_id(
        Decimal("3")
    )


def test_child_receipt_updates_parent_lifecycle_without_overstating_completion() -> None:
    parent_id = uuid4()
    lifecycle = ExecutionLifecycle(
        parent_id,
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )
    child_id = lifecycle.continuation_client_order_id(Decimal("6"))
    fill = Fill(
        client_order_id=child_id,
        instrument=InstrumentId(venue="TEST", symbol="ABC"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        price=Decimal("100"),
        filled_at=datetime.now(timezone.utc),
    )
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=child_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=fill.filled_at,
        fills=(fill,),
        correlation_id=str(parent_id),
        order_id=child_id,
        order_quantity=Decimal("6"),
    )

    updated = lifecycle.apply(receipt)

    assert updated.filled_quantity == Decimal("6")
    assert updated.remaining_quantity == Decimal("4")
    assert updated.status is OrderStatus.PARTIALLY_FILLED
    assert updated.can_continue


def test_continuation_cannot_exceed_evidenced_remainder() -> None:
    lifecycle = ExecutionLifecycle(
        uuid4(),
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    try:
        lifecycle.continuation_quantity(Decimal("7"))
    except ValueError as exc:
        assert "exceeds remaining" in str(exc)
    else:
        raise AssertionError("expected continuation quantity validation")


def test_partial_continuation_executes_remaining_quantity_with_parent_correlation() -> None:
    from quantx.domain.accounts import AccountId
    from quantx.domain.clock import FixedClock
    from quantx.domain.deployment import (
        ExecutionContext,
        ExecutionMode,
        PortfolioId,
        StrategyDeploymentId,
    )
    from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
    from quantx.domain.order_intents import TradeIntent
    from quantx.domain.risk import RiskDecision, RiskResult
    from quantx.execution.market_data import MarketSnapshot
    from quantx.execution.paper import PaperExecutionEngine
    from datetime import UTC, datetime

    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("p-1"),
        deployment_id=StrategyDeploymentId("d-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=context,
    )
    from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent

    request = ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
    )
    lifecycle = ExecutionLifecycle(
        request.order.client_order_id,
        Decimal("10"),
        Decimal("4"),
        OrderStatus.PARTIALLY_FILLED,
    )
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    receipt = engine.continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=MarketSnapshot(
            instrument=request.order.instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            ask=Decimal("100"),
        ),
    )
    assert receipt.client_order_id != request.order.client_order_id
    assert receipt.correlation_id == str(request.order.client_order_id)
    assert receipt.filled_quantity == Decimal("6")
