from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus, OrderType
from quantx.domain.orders import Fill, Order
from quantx.domain.value_objects import InstrumentId
from quantx.execution.charges import ChargeBreakdown
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt


def test_receipt_requires_charge_total_to_match_fee() -> None:
    from quantx.execution.charges import ChargeBreakdown, ChargeComponent

    with pytest.raises(ValueError, match="charges total must equal receipt fee"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=uuid4(),
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=datetime.now(UTC),
            fee=Decimal("2"),
            charges=ChargeBreakdown(
                currency="INR",
                components=(ChargeComponent("modeled_fee", Decimal("1")),),
                model_id="test.paper.charges",
                model_version="1",
            ),
        )


def test_receipt_from_order_preserves_charge_breakdown() -> None:
    from quantx.execution.charges import ChargeBreakdown, ChargeComponent

    order = _order(quantity=Decimal("1"))
    charges = ChargeBreakdown(
        currency="INR",
        components=(ChargeComponent("modeled_fee", Decimal("1")),),
        model_id="test.paper.charges",
        model_version="1",
    )
    receipt = ExecutionReceipt.from_order(
        order,
        request_id=uuid4(),
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime.now(UTC),
        fills=(_fill(order, quantity=order.quantity),),
        fee=Decimal("1"),
        charges=charges,
    )
    assert receipt.charges == charges


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
    instrument: InstrumentId | None = None,
) -> Order:
    return Order(
        instrument=instrument or InstrumentId("NSE", "TCS"),
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


def _multi_fill_receipt(
    *,
    fee: Decimal = Decimal("0"),
    per_fill_charges: tuple[ChargeBreakdown, ...] = (),
    charges: ChargeBreakdown | None = None,
) -> ExecutionReceipt:
    client_id = uuid4()
    fills = (
        Fill(
            client_order_id=client_id,
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("100"),
        ),
        Fill(
            client_order_id=client_id,
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("101"),
        ),
    )
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime.now(UTC),
        fills=fills,
        fee=fee,
        charges=charges,
        per_fill_charges=per_fill_charges,
        order_quantity=Decimal("2"),
    )


def test_receipt_retains_unrounded_per_fill_breakdowns_and_rounded_totals() -> None:
    from quantx.execution.charges import ChargeComponent

    breakdowns = (
        ChargeBreakdown(
            currency="INR",
            components=(ChargeComponent("brokerage", Decimal("0.005")),),
            model_id="schedule.test",
            model_version="1",
            rounded_total=Decimal("0.00"),
        ),
        ChargeBreakdown(
            currency="INR",
            components=(ChargeComponent("brokerage", Decimal("0.005")),),
            model_id="schedule.test",
            model_version="1",
            rounded_total=Decimal("0.00"),
        ),
    )
    receipt = _multi_fill_receipt(fee=Decimal("0.00"), per_fill_charges=breakdowns)

    assert tuple(item.total for item in receipt.per_fill_charges) == (
        Decimal("0.005"),
        Decimal("0.005"),
    )
    assert receipt.resolve_per_fill_fees() == (Decimal("0.00"), Decimal("0.00"))
    assert sum(item.total for item in receipt.per_fill_charges) == Decimal("0.010")


def test_receipt_rejects_per_fill_charge_length_and_total_mismatch() -> None:
    from quantx.execution.charges import ChargeComponent

    one = ChargeBreakdown(
        currency="INR",
        components=(ChargeComponent("fee", Decimal("1")),),
        model_id="schedule.test",
        model_version="1",
        rounded_total=Decimal("1"),
    )
    with pytest.raises(ValueError, match="length must match"):
        _multi_fill_receipt(fee=Decimal("1"), per_fill_charges=(one,))
    two = replace(one, rounded_total=Decimal("0.50"))
    with pytest.raises(ValueError, match="must equal receipt fee"):
        _multi_fill_receipt(fee=Decimal("0.50"), per_fill_charges=(one, two))


def test_legacy_multi_fill_nonzero_aggregate_fee_fails_closed() -> None:
    receipt = _multi_fill_receipt(fee=Decimal("2"))
    with pytest.raises(ValueError, match="cannot be allocated across multiple fills"):
        receipt.resolve_per_fill_fees()


def test_legacy_multi_fill_zero_fee_resolves_to_zero_per_fill() -> None:
    receipt = _multi_fill_receipt()
    assert receipt.resolve_per_fill_fees() == (Decimal("0"), Decimal("0"))


def test_legacy_single_fill_aggregate_fee_is_unambiguous() -> None:
    receipt = _multi_fill_receipt()
    single = replace(
        receipt,
        fills=receipt.fills[:1],
        fee=Decimal("1"),
        order_quantity=Decimal("1"),
    )
    assert single.resolve_per_fill_fees() == (Decimal("1"),)


def test_cumulative_observation_fee_cannot_be_allocated_without_fills() -> None:
    from quantx.execution.receipts.models import ExecutionEvidenceKind

    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime.now(UTC),
        fee=Decimal("1"),
        evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
        observed_filled_quantity=Decimal("1"),
    )
    with pytest.raises(ValueError, match="cannot be allocated without fills"):
        receipt.resolve_per_fill_fees()


def test_receipt_from_order_preserves_per_fill_charge_breakdown() -> None:
    from quantx.execution.charges import ChargeComponent

    order = _order(quantity=Decimal("1"))
    breakdown = ChargeBreakdown(
        currency="INR",
        components=(ChargeComponent("brokerage", Decimal("0.005")),),
        model_id="schedule.test",
        model_version="1",
        rounded_total=Decimal("0.00"),
    )
    receipt = ExecutionReceipt.from_order(
        order,
        request_id=uuid4(),
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime.now(UTC),
        fills=(_fill(order, quantity=order.quantity),),
        fee=Decimal("0.00"),
        per_fill_charges=(breakdown,),
    )
    assert receipt.per_fill_charges == (breakdown,)
