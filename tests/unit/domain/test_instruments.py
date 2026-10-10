import json
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.value_objects import InstrumentId


def market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def make_instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE", "NIFTY"),
        symbol="NIFTY",
        asset_class=AssetClass.INDEX,
        market=market(),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def test_instrument_rejects_non_positive_tick_size() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        Instrument(
            instrument_id=InstrumentId("NSE", "NIFTY"),
            symbol="NIFTY",
            asset_class=AssetClass.INDEX,
            market=market(),
            currency="INR",
            tick_size=Decimal("0"),
            lot_size=Decimal("1"),
        )


def test_contract_accepts_call_option_metadata() -> None:
    contract = Contract(
        instrument=make_instrument(),
        underlying=InstrumentId("NSE", "NIFTY"),
        strike=Decimal("25000"),
        option_type="call",
    )
    assert contract.option_type == "call"


def test_contract_rejects_invalid_option_type() -> None:
    with pytest.raises(ValueError, match="option_type"):
        Contract(instrument=make_instrument(), option_type="future")


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (MarketRegion.INDIA, "INDIA"),
        (MarketRegion.GLOBAL, "GLOBAL"),
        (MarketFamily.EQUITY, "EQUITY"),
        (MarketFamily.OTHER, "OTHER"),
    ],
)
def test_market_enums_stringify_to_their_values(member, value):
    assert str(member) == value
    assert format(member) == value
    assert f"{member}" == value
    assert "%s" % member == value  # noqa: UP031 -- pins printf-style formatting behavior


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (MarketRegion.INDIA, "INDIA"),
        (MarketFamily.EQUITY, "EQUITY"),
    ],
)
def test_market_enums_match_hash_and_serialize_like_their_values(member, value):
    assert member == value
    assert hash(member) == hash(value)
    assert json.dumps(member) == json.dumps(value)


@pytest.mark.parametrize(
    ("enum_type", "value", "expected"),
    [
        (MarketRegion, "INDIA", MarketRegion.INDIA),
        (MarketFamily, "EQUITY", MarketFamily.EQUITY),
    ],
)
def test_market_enums_reconstruct_from_string_values(enum_type, value, expected):
    assert enum_type(value) is expected


def test_market_context_preserves_region_and_family_values() -> None:
    context = market()
    assert context.region == MarketRegion.INDIA
    assert context.family == MarketFamily.EQUITY
    assert context.region.value == "INDIA"
    assert context.family.value == "EQUITY"
