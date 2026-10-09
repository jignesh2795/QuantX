from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.execution.accounting import PositionLedgerEntry
from quantx.execution.margin_policy import FixedPerUnitMarginPolicy


def _entry(quantity: str) -> PositionLedgerEntry:
    instrument = Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )
    return PositionLedgerEntry(
        instrument=instrument.instrument_id,
        quantity=Decimal(quantity),
        average_price=Decimal("100"),
    )


def test_fixed_per_unit_margin_scales_with_absolute_position() -> None:
    policy = FixedPerUnitMarginPolicy(Decimal("120"))
    assert policy.required_margin(_entry("10")) == Decimal("1200")
    assert policy.required_margin(_entry("-5")) == Decimal("600")
    assert policy.required_margin(_entry("0")) == Decimal("0")


def test_fixed_per_unit_margin_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="amount_per_unit"):
        FixedPerUnitMarginPolicy(Decimal("-1"))
