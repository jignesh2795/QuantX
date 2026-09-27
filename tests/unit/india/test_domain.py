from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import MarketFamily
from quantx.domain.value_objects import InstrumentId
from quantx.india import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    OptionContractSpec,
    ProductType,
)


def test_indian_exchange_mapping_and_default_instrument_metadata() -> None:
    nse = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )
    bse = IndianInstrumentSpec(
        instrument_id=InstrumentId("BSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.BSE,
        segment=IndianSegment.EQUITY,
    )
    mcx = IndianInstrumentSpec(
        instrument_id=InstrumentId("MCX", "CRUDEOIL"),
        symbol="CRUDEOIL",
        asset_class=AssetClass.COMMODITY,
        exchange=IndianExchange.MCX,
        segment=IndianSegment.COMMODITY,
    )

    assert nse.to_instrument().market.venue == "NSE"
    assert bse.to_instrument().market.venue == "BSE"
    assert mcx.to_instrument().market.venue == "MCX"
    assert nse.to_instrument().market.family is MarketFamily.EQUITY
    assert mcx.to_instrument().market.family is MarketFamily.COMMODITIES

    assert nse.currency == "INR"
    assert nse.tick_size == Decimal("0.05")
    assert nse.lot_size == Decimal("1")
    assert nse.multiplier == Decimal("1")


@pytest.mark.parametrize(
    ("asset_class", "segment", "expected_family"),
    [
        (AssetClass.EQUITY, IndianSegment.EQUITY, MarketFamily.EQUITY),
        (AssetClass.FUTURE, IndianSegment.DERIVATIVES, MarketFamily.DERIVATIVES),
        (AssetClass.OPTION, IndianSegment.DERIVATIVES, MarketFamily.DERIVATIVES),
        (AssetClass.FX, IndianSegment.CURRENCY, MarketFamily.FX),
        (AssetClass.COMMODITY, IndianSegment.COMMODITY, MarketFamily.COMMODITIES),
    ],
)
def test_indian_asset_and_segment_map_to_canonical_market_family(
    asset_class: AssetClass,
    segment: IndianSegment,
    expected_family: MarketFamily,
) -> None:
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TEST"),
        symbol="TEST",
        asset_class=asset_class,
        exchange=IndianExchange.NSE,
        segment=segment,
    )

    assert spec.to_instrument().market.family is expected_family


def test_future_spec_derives_canonical_contract() -> None:
    expiry = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "NIFTY26DEC"),
        symbol="NIFTY26DEC",
        asset_class=AssetClass.FUTURE,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.DERIVATIVES,
        lot_size=Decimal("65"),
        expiry=expiry,
    )

    contract = spec.to_contract()

    assert contract is not None
    assert contract.instrument.instrument_id == spec.instrument_id
    assert contract.instrument.market.family is MarketFamily.DERIVATIVES
    assert contract.expiry == expiry
    assert contract.strike is None
    assert contract.option_type is None


def test_option_spec_derives_canonical_contract() -> None:
    expiry = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "NIFTY26123000CE"),
        symbol="NIFTY26123000CE",
        asset_class=AssetClass.OPTION,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.DERIVATIVES,
        lot_size=Decimal("65"),
        expiry=expiry,
        strike=Decimal("23000"),
        option_type="CALL",
    )

    contract = spec.to_contract()

    assert contract is not None
    assert contract.instrument.instrument_id == spec.instrument_id
    assert contract.expiry == expiry
    assert contract.strike == Decimal("23000")
    assert contract.option_type == "CALL"


def test_option_contract_spec_validates_contract_metadata() -> None:
    spec = OptionContractSpec(
        underlying=InstrumentId("NSE", "NIFTY"),
        expiry=datetime(2026, 12, 31, tzinfo=UTC),
        strike=Decimal("23000"),
        option_type="put",
        lot_size=Decimal("65"),
    )

    assert spec.option_type == "put"

    with pytest.raises(ValueError, match="strike must be positive"):
        OptionContractSpec(
            underlying=spec.underlying,
            expiry=spec.expiry,
            strike=Decimal("0"),
            option_type="PUT",
            lot_size=spec.lot_size,
        )

    with pytest.raises(ValueError, match="option_type must be CALL or PUT"):
        OptionContractSpec(
            underlying=spec.underlying,
            expiry=spec.expiry,
            strike=spec.strike,
            option_type="STRADDLE",
            lot_size=spec.lot_size,
        )


def test_non_derivative_spec_has_no_contract() -> None:
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )

    assert spec.to_contract() is None


def test_product_type_contract_is_exported() -> None:
    assert ProductType.MIS.value == "MIS"


def test_derivative_contract_metadata_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="derivative expiry must be supplied"):
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "NIFTY"),
            symbol="NIFTY",
            asset_class=AssetClass.FUTURE,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.DERIVATIVES,
        ).to_contract()

    with pytest.raises(ValueError, match="derivative expiry must be timezone-aware"):
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "NIFTY"),
            symbol="NIFTY",
            asset_class=AssetClass.FUTURE,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.DERIVATIVES,
            expiry=datetime(2026, 12, 31),
        ).to_contract()

    expiry = datetime(2026, 12, 31, tzinfo=UTC)
    with pytest.raises(ValueError, match="option strike must be supplied"):
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "NIFTYCE"),
            symbol="NIFTYCE",
            asset_class=AssetClass.OPTION,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.DERIVATIVES,
            expiry=expiry,
            option_type="CALL",
        ).to_contract()

    with pytest.raises(ValueError, match="option_type must be supplied"):
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "NIFTY23000"),
            symbol="NIFTY23000",
            asset_class=AssetClass.OPTION,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.DERIVATIVES,
            expiry=expiry,
            strike=Decimal("23000"),
        ).to_contract()

    with pytest.raises(ValueError, match="futures must not define"):
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "NIFTY26DEC"),
            symbol="NIFTY26DEC",
            asset_class=AssetClass.FUTURE,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.DERIVATIVES,
            expiry=expiry,
            strike=Decimal("23000"),
        ).to_contract()
