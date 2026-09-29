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
    assert lifecycle.continuation_client_order_id(Decimal("6")) == lifecycle.continuation_client_order_id(Decimal("6"))


def test_continuation_identity_changes_after_new_fill() -> None:
    order_id = uuid4()
    first = ExecutionLifecycle(order_id, Decimal("10"), Decimal("4"), OrderStatus.PARTIALLY_FILLED)
    second = ExecutionLifecycle(order_id, Decimal("10"), Decimal("7"), OrderStatus.PARTIALLY_FILLED)
    assert first.continuation_client_order_id(Decimal("6")) != second.continuation_client_order_id(Decimal("3"))


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
