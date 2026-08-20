from decimal import Decimal

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
