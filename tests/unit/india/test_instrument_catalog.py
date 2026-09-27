from decimal import Decimal

from quantx.domain.enums import AssetClass
from quantx.domain.value_objects import InstrumentId
from quantx.india import (
    IndianExchange,
    IndianInstrumentCatalog,
    IndianInstrumentSpec,
    IndianSegment,
)


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


def _infy_spec() -> IndianInstrumentSpec:
    return IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "INFY"),
        symbol="INFY",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )


def test_catalog_resolves_canonical_instrument_from_indian_spec() -> None:
    spec = _tcs_spec()
    catalog = IndianInstrumentCatalog((spec,))

    instrument = catalog.resolve(spec.instrument_id)

    assert instrument is not None
    assert instrument.instrument_id == spec.instrument_id
    assert instrument.symbol == "TCS"
    assert instrument.market.venue == "NSE"
    assert instrument.currency == "INR"
    assert instrument.tick_size == Decimal("0.05")
    assert instrument.lot_size == Decimal("1")


def test_catalog_returns_none_for_unknown_instrument() -> None:
    catalog = IndianInstrumentCatalog((_tcs_spec(),))

    assert catalog.resolve(InstrumentId("NSE", "INFY")) is None


def test_catalog_add_updates_reference_data_without_changing_registry_contract() -> None:
    catalog = IndianInstrumentCatalog((_tcs_spec(),))

    catalog.add(_infy_spec())

    instrument = catalog.resolve(InstrumentId("NSE", "INFY"))

    assert instrument is not None
    assert instrument.symbol == "INFY"
    assert instrument.market.venue == "NSE"
