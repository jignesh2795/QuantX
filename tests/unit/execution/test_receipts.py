from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus, OrderType
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
        executed_at=datetime.now(UTC),
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


def test_filled_receipt_requires_a_fill() -> None:
    with pytest.raises(ValueError, match="at least one fill"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
        )


def test_partial_receipt_requires_a_fill() -> None:
    with pytest.raises(ValueError, match="at least one fill"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=datetime.now(UTC),
        )


def _order(
    *,
    quantity: Decimal = Decimal("2"),
    side: OrderSide = OrderSide.BUY,
    instrument: InstrumentId = InstrumentId("NSE", "TCS"),
) -> Order:
    return Order(
        instrument=instrument,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )


def _fill(
    order: Order,
    *,
    quantity: Decimal,
    side: OrderSide | None = None,
    instrument: InstrumentId | None = None,
    execution_id=None,
) -> Fill:
    return Fill(
        client_order_id=order.client_order_id,
        instrument=instrument or order.instrument,
        side=side or order.side,
        quantity=quantity,
        price=Decimal("100"),
        execution_id=execution_id or uuid4(),
    )


def test_receipt_from_order_accepts_matching_full_fill() -> None:
    order = _order()
    receipt = ExecutionReceipt.from_order(
        order,
        request_id=uuid4(),
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime.now(UTC),
        fills=(_fill(order, quantity=order.quantity),),
    )
    assert receipt.fills[0].quantity == order.quantity


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"instrument": InstrumentId("NSE", "INFY")}, "order instrument"),
        ({"side": OrderSide.SELL}, "order side"),
    ],
)
def test_receipt_from_order_rejects_fill_identity_mismatch(kwargs, message) -> None:
    order = _order()
    with pytest.raises(ValueError, match=message):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
            fills=(_fill(order, quantity=order.quantity, **kwargs),),
        )


def test_receipt_from_order_rejects_excess_fill_quantity() -> None:
    order = _order(quantity=Decimal("2"))
    with pytest.raises(ValueError, match="exceed order quantity"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
            fills=(_fill(order, quantity=Decimal("2.1")),),
        )


def test_receipt_from_order_rejects_duplicate_execution_ids() -> None:
    order = _order(quantity=Decimal("2"))
    execution_id = uuid4()
    fills = (
        _fill(order, quantity=Decimal("1"), execution_id=execution_id),
        _fill(order, quantity=Decimal("1"), execution_id=execution_id),
    )
    with pytest.raises(ValueError, match="unique execution_id"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
            fills=fills,
        )


def test_receipt_from_order_requires_full_quantity_for_filled() -> None:
    order = _order(quantity=Decimal("2"))
    with pytest.raises(ValueError, match="equal order quantity"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.FILLED,
            order_status=OrderStatus.FILLED,
            executed_at=datetime.now(UTC),
            fills=(_fill(order, quantity=Decimal("1")),),
        )


def test_receipt_from_order_requires_partial_quantity_for_partial() -> None:
    order = _order(quantity=Decimal("2"))
    with pytest.raises(ValueError, match="between zero and order quantity"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=datetime.now(UTC),
            fills=(_fill(order, quantity=order.quantity),),
        )
