from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.cash_ledger import CashLedger


def _fill(side: OrderSide, quantity: str, price: str) -> Fill:
    return Fill(
        client_order_id=uuid4(),
        instrument=InstrumentId("NSE", "TCS"),
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
    )


def test_buy_reduces_cash_and_fee_is_cash_outflow() -> None:
    ledger = CashLedger(Money(Decimal("5000"), "INR"))

    entry = ledger.apply(_fill(OrderSide.BUY, "10", "100"), fee=Decimal("1"))

    assert entry.notional.amount == Decimal("1000")
    assert entry.trade_cash_flow.amount == Decimal("-1000")
    assert entry.fee.amount == Decimal("1")
    assert entry.net_cash_flow.amount == Decimal("-1001")
    assert entry.cash_after.amount == Decimal("3999")
    assert ledger.balance.amount == Decimal("3999")


def test_duplicate_fill_is_idempotent() -> None:
    ledger = CashLedger(Money(Decimal("5000"), "INR"))
    fill = _fill(OrderSide.BUY, "10", "100")

    first = ledger.apply(fill, fee=Decimal("1"))
    second = ledger.apply(fill, fee=Decimal("1"))

    assert second == first
    assert ledger.balance.amount == Decimal("3999")
    assert ledger.entries() == (first,)


def test_duplicate_execution_id_with_conflicting_fee_is_rejected() -> None:
    ledger = CashLedger(Money(Decimal("5000"), "INR"))
    fill = _fill(OrderSide.BUY, "10", "100")
    ledger.apply(fill, fee=Decimal("1"))

    with pytest.raises(ValueError, match="already applied"):
        ledger.apply(fill, fee=Decimal("2"))


def test_sell_increases_cash_after_fee() -> None:
    ledger = CashLedger(Money(Decimal("5000"), "INR"))

    entry = ledger.apply(_fill(OrderSide.SELL, "10", "100"), fee=Decimal("1"))

    assert entry.trade_cash_flow.amount == Decimal("1000")
    assert entry.net_cash_flow.amount == Decimal("999")
    assert ledger.balance.amount == Decimal("5999")


def test_cash_ledger_rejects_overdraft() -> None:
    ledger = CashLedger(Money(Decimal("500"), "INR"))

    with pytest.raises(ValueError, match="cash balance negative"):
        ledger.apply(_fill(OrderSide.BUY, "10", "100"), fee=Decimal("1"))


def test_derivative_multiplier_is_applied_to_notional() -> None:
    ledger = CashLedger(Money(Decimal("100000"), "INR"))

    entry = ledger.apply(
        _fill(OrderSide.BUY, "2", "1000"),
        multiplier=Decimal("50"),
    )

    assert entry.notional.amount == Decimal("100000")
    assert entry.cash_after.amount == Decimal("0")
