from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Contract, Instrument
from quantx.domain.value_objects import InstrumentId


def make_instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE:NIFTY"),
        symbol="NIFTY",
        asset_class=AssetClass.INDEX,
        venue="NSE",
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def test_instrument_rejects_non_positive_tick_size() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        Instrument(
            instrument_id=InstrumentId("NSE:NIFTY"),
            symbol="NIFTY",
            asset_class=AssetClass.INDEX,
            venue="NSE",
            currency="INR",
            tick_size=Decimal("0"),
            lot_size=Decimal("1"),
        )


def test_contract_accepts_call_option_metadata() -> None:
    contract = Contract(
        instrument=make_instrument(),
        underlying=InstrumentId("NSE:NIFTY"),
        strike=Decimal("25000"),
        option_type="call",
    )

    assert contract.option_type == "call"


def test_contract_rejects_invalid_option_type() -> None:
    with pytest.raises(ValueError, match="option_type"):
        Contract(instrument=make_instrument(), option_type="future")
