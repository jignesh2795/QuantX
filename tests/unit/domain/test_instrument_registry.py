from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry, InstrumentResolution
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId
from quantx.india import IndianExchange, IndianInstrumentSpec, IndianSegment

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
UNDERLYING = InstrumentId("NSE", "NIFTY")


def _tcs_spec() -> IndianInstrumentSpec:
    return IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _option_instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
    return Instrument(
        instrument_id=OPTION,
        symbol=OPTION.symbol,
        asset_class=AssetClass.OPTION,
        market=market,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
    )


def _option_contract() -> Contract:
    return Contract(
        instrument_id=OPTION,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
    )


def _option_resolution() -> InstrumentResolution:
    return InstrumentResolution(
        instrument=_option_instrument(),
        contract=_option_contract(),
        instrument_rule_version="rule-v1",
        instrument_rule_effective_from=T0,
        resolved_at=T0,
        contract_metadata_version="contract-v1",
        contract_source="nse-bhavcopy",
        contract_effective_from=T0,
    )


def test_indian_spec_round_trips_through_in_memory_registry() -> None:
    instrument = _tcs_spec().to_instrument()
    registry = InMemoryInstrumentRegistry((instrument,))

    resolved = registry.resolve(instrument.instrument_id)

    assert resolved == instrument
    assert resolved is not None
    assert resolved.market.venue == "NSE"
    assert resolved.currency == "INR"


def test_registry_returns_none_for_unknown_instrument() -> None:
    registry = InMemoryInstrumentRegistry((_tcs_spec().to_instrument(),))

    assert registry.resolve(InstrumentId("NSE", "INFY")) is None


def test_derivative_resolution_requires_complete_contract_metadata() -> None:
    # The risk boundary relies on the canonical type to refuse an incomplete
    # derivative claim, so it can never approve metadata the type would accept
    # only because fields were silently omitted.
    with pytest.raises(ValueError, match="requires canonical contract metadata"):
        InstrumentResolution(
            instrument=_option_instrument(),
            instrument_rule_version="rule-v1",
            instrument_rule_effective_from=T0,
            resolved_at=T0,
        )


def test_derivative_resolution_requires_metadata_version_and_provenance() -> None:
    resolution = _option_resolution()

    with pytest.raises(ValueError, match="requires a contract metadata version"):
        InstrumentResolution(
            instrument=resolution.instrument,
            contract=resolution.contract,
            instrument_rule_version="rule-v1",
            instrument_rule_effective_from=T0,
            resolved_at=T0,
            contract_source="nse-bhavcopy",
            contract_effective_from=T0,
        )
    with pytest.raises(ValueError, match="requires contract metadata provenance"):
        InstrumentResolution(
            instrument=resolution.instrument,
            contract=resolution.contract,
            instrument_rule_version="rule-v1",
            instrument_rule_effective_from=T0,
            resolved_at=T0,
            contract_metadata_version="contract-v1",
            contract_effective_from=T0,
        )


def test_non_derivative_resolution_must_not_carry_a_contract() -> None:
    with pytest.raises(ValueError, match="non-derivative instrument resolution"):
        InstrumentResolution(
            instrument=_tcs_spec().to_instrument(),
            contract=_option_contract(),
            instrument_rule_version="rule-v1",
            instrument_rule_effective_from=T0,
            resolved_at=T0,
            contract_metadata_version="contract-v1",
            contract_source="nse-bhavcopy",
            contract_effective_from=T0,
        )


def test_resolution_requires_a_rule_identity_effective_at_the_instant() -> None:
    with pytest.raises(ValueError, match="not effective at the resolution timestamp"):
        InstrumentResolution(
            instrument=_option_instrument(),
            contract=_option_contract(),
            instrument_rule_version="rule-v1",
            instrument_rule_effective_from=datetime(2026, 2, 1, tzinfo=UTC),
            resolved_at=T0,
            contract_metadata_version="contract-v1",
            contract_source="nse-bhavcopy",
            contract_effective_from=T0,
        )
