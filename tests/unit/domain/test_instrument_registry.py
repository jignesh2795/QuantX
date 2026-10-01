from decimal import Decimal

from quantx.domain.enums import AssetClass
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.value_objects import InstrumentId
from quantx.india import IndianExchange, IndianInstrumentSpec, IndianSegment


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
