from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt


def _partial(order_id, quantity):
    fill = Fill(
        client_order_id=order_id,
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        price=Decimal("100"),
        filled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        order_status=OrderStatus.PARTIALLY_FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        order_id=order_id,
        order_quantity=Decimal("10"),
        fills=(fill,),
    )


def test_partial_receipt_exposes_remaining_quantity() -> None:
    receipt = _partial(uuid4(), "4")
    assert receipt.filled_quantity == Decimal("4")
    assert receipt.remaining_quantity == Decimal("6")


def test_execution_lifecycle_accumulates_partial_fills() -> None:
    order_id = uuid4()
    lifecycle = ExecutionLifecycle(order_id, Decimal("10"))
    updated = lifecycle.apply(_partial(order_id, "4"))
    assert updated.remaining_quantity == Decimal("6")

    completed = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        order_id=order_id,
        order_quantity=Decimal("10"),
        fills=(
            Fill(
                client_order_id=order_id,
                instrument=InstrumentId("NSE", "TCS"),
                side=OrderSide.BUY,
                quantity=Decimal("6"),
                price=Decimal("101"),
                filled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ),
    )
    updated = updated.apply(completed)
    assert updated.filled_quantity == Decimal("10")
    assert updated.remaining_quantity == Decimal("0")
    assert updated.is_complete
