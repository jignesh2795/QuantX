from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import OptionType
from quantx.domain.value_objects import InstrumentId
from quantx.india import (
    IndianExchange,
    IndianInstrumentCatalog,
    IndianInstrumentSpec,
    IndianSegment,
)
from quantx.research.market_rules import (
    PointInTimeContractCatalog,
    PointInTimeInstrumentRegistry,
    PointInTimeInstrumentResolver,
    VersionedContractMetadata,
    VersionedInstrumentRule,
)

EXPIRY = datetime(2026, 1, 29, 15, 30, tzinfo=UTC)
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


def _infy_spec() -> IndianInstrumentSpec:
    return IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "INFY"),
        symbol="INFY",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )


def _option_spec(**overrides) -> IndianInstrumentSpec:
    values: dict = {
        "instrument_id": InstrumentId("NSE", "NIFTY26JAN25000CE"),
        "symbol": "NIFTY26JAN25000CE",
        "asset_class": AssetClass.OPTION,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.DERIVATIVES,
        "lot_size": Decimal("25"),
        "underlying": UNDERLYING,
        "expiry": EXPIRY,
        "strike": Decimal("25000"),
        "option_type": "call",
    }
    values.update(overrides)
    return IndianInstrumentSpec(**values)


def _future_spec(**overrides) -> IndianInstrumentSpec:
    values: dict = {
        "instrument_id": InstrumentId("NSE", "NIFTY26JANFUT"),
        "symbol": "NIFTY26JANFUT",
        "asset_class": AssetClass.FUTURE,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.DERIVATIVES,
        "lot_size": Decimal("25"),
        "underlying": UNDERLYING,
        "expiry": EXPIRY,
    }
    values.update(overrides)
    return IndianInstrumentSpec(**values)


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


def test_catalog_registers_canonical_option_contract() -> None:
    spec = _option_spec()
    catalog = IndianInstrumentCatalog((spec,))

    contract = catalog.resolve_contract(spec.instrument_id)

    assert contract is not None
    assert contract.instrument_id == spec.instrument_id
    assert contract.asset_class is AssetClass.OPTION
    assert contract.underlying == UNDERLYING
    assert contract.expiry == EXPIRY
    assert contract.strike == Decimal("25000")
    assert contract.option_type is OptionType.CALL
    assert catalog.resolve(spec.instrument_id) is not None


def test_catalog_contract_round_trips_through_point_in_time_resolution() -> None:
    spec = _option_spec()
    catalog = IndianInstrumentCatalog((spec,))
    contract = catalog.resolve_contract(spec.instrument_id)
    assert contract is not None
    effective_from = datetime(2026, 1, 1, tzinfo=UTC)
    resolved_at = datetime(2026, 1, 5, tzinfo=UTC)
    resolver = PointInTimeInstrumentResolver(
        instruments=catalog,
        rules=PointInTimeInstrumentRegistry(
            (
                VersionedInstrumentRule(
                    instrument_id=str(spec.instrument_id),
                    effective_from=effective_from,
                    effective_to=None,
                    tick_size=spec.tick_size,
                    lot_size=spec.lot_size,
                    multiplier=spec.multiplier,
                    currency=spec.currency,
                    rule_version="rule-v1",
                ),
            )
        ),
        contracts=PointInTimeContractCatalog(
            (
                VersionedContractMetadata(
                    contract=contract,
                    effective_from=effective_from,
                    effective_to=None,
                    metadata_version="contract-v1",
                    source="nse-bhavcopy",
                ),
            )
        ),
    )

    resolution = resolver.resolve_at(spec.instrument_id, resolved_at)

    assert resolution.instrument == catalog.resolve(spec.instrument_id)
    assert resolution.contract == contract
    assert resolution.contract is not None
    assert resolution.contract.underlying == UNDERLYING
    assert resolution.contract.expiry == EXPIRY
    assert resolution.contract.strike == Decimal("25000")
    assert resolution.contract.option_type is OptionType.CALL
    assert resolution.contract_metadata_version == "contract-v1"
    assert resolution.contract_source == "nse-bhavcopy"


def test_catalog_registers_canonical_future_contract() -> None:
    spec = _future_spec()
    catalog = IndianInstrumentCatalog((spec,))

    contract = catalog.resolve_contract(spec.instrument_id)

    assert contract is not None
    assert contract.asset_class is AssetClass.FUTURE
    assert contract.strike is None
    assert contract.option_type is None


def test_non_derivative_catalog_entry_has_no_contract() -> None:
    catalog = IndianInstrumentCatalog((_tcs_spec(),))

    assert catalog.resolve_contract(InstrumentId("NSE", "TCS")) is None


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (_option_spec(strike=None), "option strike must be supplied"),
        (
            _option_spec(option_type=None),
            "option_type must be supplied",
        ),
        (_future_spec(strike=Decimal("25000")), "futures must not define"),
        (
            _future_spec(option_type="CALL"),
            "futures must not define",
        ),
        (
            _option_spec(expiry=datetime(2026, 1, 29, 15, 30)),
            "timezone-aware",
        ),
        (_option_spec(expiry=None), "derivative expiry must be supplied"),
        (_option_spec(underlying=None), "derivative underlying must be supplied"),
    ],
)
def test_catalog_rejects_incomplete_derivative_at_registration(
    spec: IndianInstrumentSpec,
    message: str,
) -> None:
    catalog = IndianInstrumentCatalog()

    with pytest.raises(ValueError, match=message):
        catalog.add(spec)

    # Registration is atomic: a rejected spec leaves no partial entry.
    assert catalog.resolve(spec.instrument_id) is None
    assert catalog.resolve_contract(spec.instrument_id) is None


def test_reusing_an_identity_for_a_non_derivative_clears_contract_metadata() -> None:
    option = _option_spec()
    catalog = IndianInstrumentCatalog((option,))
    assert catalog.resolve_contract(option.instrument_id) is not None

    catalog.add(
        IndianInstrumentSpec(
            instrument_id=option.instrument_id,
            symbol=option.symbol,
            asset_class=AssetClass.EQUITY,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
        )
    )

    instrument = catalog.resolve(option.instrument_id)
    assert instrument is not None
    assert instrument.asset_class is AssetClass.EQUITY
    assert catalog.resolve_contract(option.instrument_id) is None
