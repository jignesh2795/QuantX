from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument
from quantx.domain.positions import Position
from quantx.domain.value_objects import InstrumentId


def instrument(asset_class: AssetClass = AssetClass.EQUITY) -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE:RELIANCE"),
        symbol="RELIANCE",
        asset_class=asset_class,
        venue="NSE",
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
        multiplier=Decimal("1"),
    )


def test_position_notional_is_market_independent() -> None:
    position = Position(
        instrument=instrument(),
        quantity=Decimal("10"),
        average_price=Decimal("2500"),
    )

    assert position.notional == Decimal("25000")
    assert position.is_long
    assert not position.is_short


def test_short_position_is_detected() -> None:
    position = Position(
        instrument=instrument(),
        quantity=Decimal("-2"),
        average_price=Decimal("100"),
    )

    assert position.is_short
    assert not position.is_long
    assert position.notional == Decimal("200")


def test_flat_position_is_detected() -> None:
    position = Position(
        instrument=instrument(),
        quantity=Decimal("0"),
        average_price=Decimal("100"),
    )

    assert position.is_flat


def test_derivative_detection_uses_asset_class() -> None:
    future = Position(
        instrument=instrument(AssetClass.FUTURE),
        quantity=Decimal("1"),
        average_price=Decimal("20000"),
    )

    assert future.is_derivative


def test_negative_average_price_is_rejected() -> None:
    with pytest.raises(ValueError):
        Position(
            instrument=instrument(),
            quantity=Decimal("1"),
            average_price=Decimal("-1"),
        )
