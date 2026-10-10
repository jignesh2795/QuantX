from decimal import Decimal

import pytest

from quantx.domain.enums import OrderSide
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.accounting import FillAccounting


def test_average_cost_buy_and_partial_sell_realizes_pnl() -> None:
    instrument = InstrumentId("NSE", "TCS")
    accounting = FillAccounting()

    accounting.apply(
        Fill(
            client_order_id=__import__("uuid").uuid4(),
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("100"),
        )
    )
    entry = accounting.apply(
        Fill(
            client_order_id=__import__("uuid").uuid4(),
            instrument=instrument,
            side=OrderSide.SELL,
            quantity=Decimal("4"),
            price=Decimal("110"),
        )
    )

    assert entry.quantity == Decimal("6")
    assert entry.average_price == Decimal("100")
    assert entry.realized_pnl == Decimal("40")


def test_duplicate_fill_is_idempotent_with_same_fee() -> None:
    instrument = InstrumentId("NSE", "TCS")
    accounting = FillAccounting()
    execution_id = __import__("uuid").uuid4()
    fill = Fill(
        client_order_id=__import__("uuid").uuid4(),
        instrument=instrument,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("100"),
        execution_id=execution_id,
    )

    first = accounting.apply(fill, fee=Decimal("1"))
    second = accounting.apply(fill, fee=Decimal("1"))

    assert second == first
    assert accounting.get(instrument) == first
    assert len(accounting.snapshot()) == 1


def test_duplicate_execution_id_with_conflicting_fill_data_is_rejected() -> None:
    instrument = InstrumentId("NSE", "TCS")
    accounting = FillAccounting()
    execution_id = __import__("uuid").uuid4()
    first = Fill(
        client_order_id=__import__("uuid").uuid4(),
        instrument=instrument,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("100"),
        execution_id=execution_id,
    )
    conflicting = Fill(
        client_order_id=first.client_order_id,
        instrument=instrument,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("101"),
        execution_id=execution_id,
    )

    accounting.apply(first)
    with pytest.raises(ValueError, match="already applied"):
        accounting.apply(conflicting)


def test_reversal_starts_new_average_at_reversal_price() -> None:
    instrument = InstrumentId("NSE", "TCS")
    accounting = FillAccounting()
    accounting.apply(
        Fill(__import__("uuid").uuid4(), instrument, OrderSide.BUY, Decimal("10"), Decimal("100"))
    )
    entry = accounting.apply(
        Fill(__import__("uuid").uuid4(), instrument, OrderSide.SELL, Decimal("15"), Decimal("110"))
    )

    assert entry.quantity == Decimal("-5")
    assert entry.average_price == Decimal("110")
    assert entry.realized_pnl == Decimal("100")
