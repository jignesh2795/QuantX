from decimal import Decimal

import pytest

from quantx.domain.value_objects import InstrumentId, Money, ProductCode, Quantity


def test_money_is_currency_aware() -> None:
    money = Money(Decimal("10.50"), "INR")
    assert money.amount == Decimal("10.50")
    assert money.currency == "INR"


def test_money_rejects_non_decimal_amount() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "INR")  # float
    with pytest.raises(TypeError):
        Money(True, "INR")  # bool
    with pytest.raises(TypeError):
        Money("10.50", "INR")  # str
    with pytest.raises(TypeError):
        Money(10, "INR")  # int


def test_money_rejects_non_finite_decimal() -> None:
    with pytest.raises(ValueError, match="finite"):
        Money(Decimal("NaN"), "INR")
    with pytest.raises(ValueError, match="finite"):
        Money(Decimal("Infinity"), "INR")
    with pytest.raises(ValueError, match="finite"):
        Money(Decimal("-Infinity"), "INR")


def test_money_accepts_valid_finite_decimal() -> None:
    assert Money(Decimal("0"), "INR").amount == Decimal("0")
    assert Money(Decimal("10.50"), "INR").amount == Decimal("10.50")
    assert Money(Decimal("-5.25"), "USD").amount == Decimal("-5.25")


def test_money_add_same_currency() -> None:
    a = Money(Decimal("10"), "INR")
    b = Money(Decimal("5"), "INR")
    result = a + b
    assert result == Money(Decimal("15"), "INR")


def test_money_sub_same_currency() -> None:
    a = Money(Decimal("10"), "INR")
    b = Money(Decimal("3"), "INR")
    result = a - b
    assert result == Money(Decimal("7"), "INR")


def test_money_add_different_currency_raises() -> None:
    a = Money(Decimal("10"), "INR")
    b = Money(Decimal("5"), "USD")
    with pytest.raises(ValueError, match="currency mismatch"):
        a + b


def test_money_sub_different_currency_raises() -> None:
    a = Money(Decimal("10"), "INR")
    b = Money(Decimal("3"), "USD")
    with pytest.raises(ValueError, match="currency mismatch"):
        a - b


def test_money_add_non_money_raises_type_error() -> None:
    a = Money(Decimal("10"), "INR")
    with pytest.raises(TypeError):
        a + 5
    with pytest.raises(TypeError):
        a - 5


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
