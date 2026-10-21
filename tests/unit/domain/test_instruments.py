import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId

EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)


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


def test_contract_accepts_complete_call_option_metadata() -> None:
    contract = Contract(
        instrument_id=InstrumentId("NSE", "NIFTY26DEC25000CE"),
        asset_class=AssetClass.OPTION,
        underlying=InstrumentId("NSE", "NIFTY"),
        expiry=EXPIRY,
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
    )

    assert contract.option_type is OptionType.CALL
    assert contract.instrument_id == InstrumentId("NSE", "NIFTY26DEC25000CE")
    assert contract.underlying == InstrumentId("NSE", "NIFTY")


def test_contract_rejects_a_free_string_option_type() -> None:
    with pytest.raises(ValueError, match="canonical OptionType"):
        Contract(
            instrument_id=InstrumentId("NSE", "NIFTY26DEC25000CE"),
            asset_class=AssetClass.OPTION,
            underlying=InstrumentId("NSE", "NIFTY"),
            expiry=EXPIRY,
            strike=Decimal("25000"),
            option_type="CALL",
        )


def test_option_type_parse_normalizes_source_spellings() -> None:
    assert OptionType.parse("call") is OptionType.CALL
    assert OptionType.parse(" put ") is OptionType.PUT
    assert OptionType.parse(OptionType.PUT) is OptionType.PUT
    with pytest.raises(ValueError, match="CALL or PUT"):
        OptionType.parse("future")


def test_contract_payload_round_trips_losslessly() -> None:
    contract = Contract(
        instrument_id=InstrumentId("NSE", "NIFTY26DEC25000CE"),
        asset_class=AssetClass.OPTION,
        underlying=InstrumentId("NSE", "NIFTY"),
        expiry=EXPIRY,
        strike=Decimal("25000.50"),
        option_type=OptionType.PUT,
    )

    assert Contract.from_payload(contract.to_payload()) == contract


def test_instrument_payload_round_trips() -> None:
    instrument = make_instrument()

    assert Instrument.from_payload(instrument.to_payload()) == instrument


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


def test_market_context_payload_round_trips() -> None:
    context = market()

    assert MarketContext.from_payload(context.to_payload()) == context


def test_market_context_payload_rejects_unexpected_fields() -> None:
    payload = market().to_payload()
    payload["extra"] = "forged"

    with pytest.raises(ValueError, match="unexpected fields"):
        MarketContext.from_payload(payload)


def test_market_context_payload_rejects_an_unknown_market_family() -> None:
    payload = market().to_payload()
    payload["family"] = "FORGED"

    with pytest.raises(ValueError):
        MarketContext.from_payload(payload)
