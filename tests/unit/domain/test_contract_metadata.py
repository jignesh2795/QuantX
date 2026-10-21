"""Adversarial coverage for canonical derivative contract metadata (QX-05).

The tests pin the fail-closed construction contract from ADR-012: an option
needs underlying, timezone-aware expiry, a positive finite strike and the one
canonical ``OptionType``; a future needs underlying and expiry and must reject
option-only fields; a non-derivative instrument never carries a contract. The
contract references its instrument by stable ``InstrumentId`` and never embeds
a second ``Instrument`` copy.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
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
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
FUTURE = InstrumentId("NSE", "NIFTY26DECFUT")
UNDERLYING = InstrumentId("NSE", "NIFTY")


def option_contract(**overrides: object) -> Contract:
    values: dict[str, object] = {
        "instrument_id": OPTION,
        "asset_class": AssetClass.OPTION,
        "underlying": UNDERLYING,
        "expiry": EXPIRY,
        "strike": Decimal("25000"),
        "option_type": OptionType.CALL,
    }
    values.update(overrides)
    return Contract(**values)  # type: ignore[arg-type]


def future_contract(**overrides: object) -> Contract:
    values: dict[str, object] = {
        "instrument_id": FUTURE,
        "asset_class": AssetClass.FUTURE,
        "underlying": UNDERLYING,
        "expiry": EXPIRY,
    }
    values.update(overrides)
    return Contract(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("underlying", "underlying must be an InstrumentId"),
        ("expiry", "expiry must be a datetime"),
        ("strike", "option strike must be supplied"),
        ("option_type", "option_type must be supplied"),
    ],
)
def test_option_requires_complete_metadata(field: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        option_contract(**{field: None})


def test_option_rejects_naive_expiry() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        option_contract(expiry=datetime(2026, 12, 31, 15, 30))


@pytest.mark.parametrize("strike", [Decimal("0"), Decimal("-1")])
def test_option_rejects_non_positive_strike(strike: Decimal) -> None:
    with pytest.raises(ValueError, match="strike must be positive"):
        option_contract(strike=strike)


@pytest.mark.parametrize("strike", [Decimal("NaN"), Decimal("Infinity")])
def test_option_rejects_non_finite_strike(strike: Decimal) -> None:
    with pytest.raises(ValueError, match="strike must be positive"):
        option_contract(strike=strike)


def test_option_rejects_non_decimal_strike() -> None:
    with pytest.raises(ValueError, match="strike must be a Decimal"):
        option_contract(strike=25000)


def test_option_rejects_a_free_string_option_type() -> None:
    with pytest.raises(ValueError, match="canonical OptionType"):
        option_contract(option_type="CALL")


def test_option_type_vocabulary_is_exactly_call_and_put() -> None:
    assert {member.value for member in OptionType} == {"CALL", "PUT"}
    assert OptionType.parse("call") is OptionType.CALL
    assert OptionType.parse("Put") is OptionType.PUT
    with pytest.raises(ValueError, match="CALL or PUT"):
        OptionType.parse("FUTURE")


def test_future_requires_underlying_and_expiry() -> None:
    with pytest.raises(ValueError, match="underlying must be an InstrumentId"):
        future_contract(underlying=None)
    with pytest.raises(ValueError, match="expiry must be a datetime"):
        future_contract(expiry=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        future_contract(expiry=datetime(2026, 12, 31, 15, 30))


@pytest.mark.parametrize(
    "overrides",
    [{"strike": Decimal("25000")}, {"option_type": OptionType.CALL}],
)
def test_future_rejects_option_only_fields(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="futures must not define strike or option_type"):
        future_contract(**overrides)


@pytest.mark.parametrize(
    "asset_class",
    [AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF, AssetClass.FX, AssetClass.COMMODITY],
)
def test_non_derivative_asset_class_cannot_carry_a_contract(asset_class: AssetClass) -> None:
    with pytest.raises(ValueError, match="derivative asset class"):
        Contract(
            instrument_id=OPTION,
            asset_class=asset_class,
            underlying=UNDERLYING,
            expiry=EXPIRY,
        )


def test_contract_rejects_its_own_instrument_as_underlying() -> None:
    with pytest.raises(ValueError, match="underlying must differ"):
        option_contract(underlying=OPTION)


def test_contract_references_identity_instead_of_copying_the_instrument() -> None:
    contract = option_contract()

    assert not hasattr(contract, "instrument")
    assert contract.instrument_id == OPTION
    assert contract.to_payload()["instrument_id"] == {"venue": "NSE", "symbol": OPTION.symbol}


def test_option_contract_payload_round_trips_losslessly() -> None:
    contract = option_contract(strike=Decimal("25000.50"), option_type=OptionType.PUT)

    restored = Contract.from_payload(contract.to_payload())

    assert restored == contract
    assert restored.strike == Decimal("25000.50")
    assert restored.option_type is OptionType.PUT


def test_future_contract_payload_round_trips_losslessly() -> None:
    contract = future_contract()

    assert Contract.from_payload(contract.to_payload()) == contract


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("strike"),
        lambda payload: payload.update({"extra": "forged"}),
        lambda payload: payload.update({"option_type": "call"}),
        lambda payload: payload.update({"expiry": "2026-12-31T15:30:00"}),
        lambda payload: payload.update({"asset_class": "FUTURE"}),
    ],
)
def test_contract_payload_rejects_missing_or_invalid_fields(mutate) -> None:
    payload = option_contract().to_payload()
    mutate(payload)

    with pytest.raises(ValueError):
        Contract.from_payload(payload)


def test_instrument_payload_is_contract_independent() -> None:
    instrument = Instrument(
        instrument_id=UNDERLYING,
        symbol="NIFTY",
        asset_class=AssetClass.INDEX,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
        multiplier=Decimal("1"),
    )

    payload = instrument.to_payload()

    assert payload["instrument_id"] == {"venue": "NSE", "symbol": "NIFTY"}
    assert "underlying" not in payload
    assert "expiry" not in payload
    assert "strike" not in payload
    assert "option_type" not in payload
    assert Instrument.from_payload(payload) == instrument


def test_contract_payload_is_independent_of_equivalent_spelling() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    canonical = option_contract()
    respelled = option_contract(
        strike=Decimal("25000.00"),
        expiry=datetime(2026, 12, 31, 21, 0, tzinfo=ist),
    )

    assert respelled == canonical
    assert respelled.to_payload() == canonical.to_payload()
    assert Contract.from_payload(respelled.to_payload()) == canonical


def test_instrument_payload_is_independent_of_equivalent_spelling() -> None:
    instrument = Instrument(
        instrument_id=UNDERLYING,
        symbol="NIFTY",
        asset_class=AssetClass.INDEX,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
        multiplier=Decimal("1"),
    )
    respelled = replace(
        instrument,
        tick_size=Decimal("0.050"),
        lot_size=Decimal("1.0"),
        multiplier=Decimal("1.00"),
    )

    assert respelled == instrument
    assert respelled.to_payload() == instrument.to_payload()
