from decimal import Decimal

import pytest

from quantx.domain.value_objects import InstrumentId, Money, ProductCode, Quantity


def test_money_is_currency_aware() -> None:
    money = Money(Decimal("10.50"), "INR")
    assert money.amount == Decimal("10.50")
    assert money.currency == "INR"


def test_quantity_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="quantity cannot be negative"):
        Quantity(Decimal("-1"))


def test_instrument_id_string_form() -> None:
    assert str(InstrumentId("NSE", "RELIANCE")) == "NSE:RELIANCE"


def test_product_code_is_opaque_and_non_empty() -> None:
    assert str(ProductCode("CNC")) == "CNC"
    assert ProductCode("CNC") == ProductCode("CNC")


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_product_code_rejects_empty_values(value: str) -> None:
    with pytest.raises(ValueError, match="product code must not be empty"):
        ProductCode(value)
