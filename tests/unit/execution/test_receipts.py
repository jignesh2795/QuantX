from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt


def test_execution_receipt_accepts_fill_outcome() -> None:
    client_id = uuid4()
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime.now(timezone.utc),
        fills=(
            Fill(
                client_order_id=client_id,
                instrument=InstrumentId("NSE", "TCS"),
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                price=Decimal("100"),
            ),
        ),
        source="paper",
    )
    assert receipt.outcome is ExecutionOutcome.FILLED



def test_filled_receipt_requires_a_fill():
    with pytest.raises(ValueError, match="at least one fill"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(timezone.utc),
        )


def test_partial_receipt_requires_a_fill():
    with pytest.raises(ValueError, match="at least one fill"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=datetime.now(timezone.utc),
        )
