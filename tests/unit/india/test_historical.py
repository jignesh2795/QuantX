from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.india import (
    IndianExchange,
    IndianHistoricalOHLCVNormalizer,
    IndianInstrumentCatalog,
    IndianInstrumentSpec,
    IndianSegment,
)
from quantx.research.data import HistoricalDataSeries
from quantx.research.ingest import RawMarketRecord
from quantx.research.replay import HistoricalReplay


def _normalizer() -> IndianHistoricalOHLCVNormalizer:
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )
    return IndianHistoricalOHLCVNormalizer(
        catalog=IndianInstrumentCatalog((spec,)),
        instrument_id=spec.instrument_id,
        dataset_id="nse-fixture",
        dataset_version="v1",
    )


def _record() -> RawMarketRecord:
    return RawMarketRecord(
        timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=UTC),
        instrument="TCS",
        sequence=0,
        fields={
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
            "volume": 25000,
        },
        timeframe="5m",
    )


def test_indian_normalizer_preserves_candle_payload_and_catalog_identity() -> None:
    observation = _normalizer().normalize(_record())

    assert observation.instrument == InstrumentId("NSE", "TCS")
    assert isinstance(observation.snapshot, Candle)
    assert observation.snapshot.instrument == InstrumentId("NSE", "TCS")
    assert observation.snapshot.timeframe == "5m"
    assert observation.snapshot.open == Decimal("100")
    assert observation.snapshot.high == Decimal("101")
    assert observation.snapshot.low == Decimal("99")
    assert observation.snapshot.close == Decimal("100.5")
    assert observation.snapshot.volume == Decimal("25000")

    series = HistoricalDataSeries((observation,))
    assert HistoricalReplay(series).run(lambda _frame: None) == 1


def test_indian_normalizer_rejects_symbol_identity_mismatch() -> None:
    normalizer = _normalizer()

    with pytest.raises(ValueError, match="does not match"):
        normalizer.normalize(
            RawMarketRecord(
                timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=UTC),
                instrument="INFY",
                sequence=0,
                fields={
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 25000,
                },
                timeframe="5m",
            )
        )


def test_indian_normalizer_fails_closed_for_unknown_catalog_instrument() -> None:
    normalizer = IndianHistoricalOHLCVNormalizer(
        catalog=IndianInstrumentCatalog(),
        instrument_id=InstrumentId("NSE", "TCS"),
        dataset_id="nse-fixture",
        dataset_version="v1",
    )

    with pytest.raises(ValueError, match="unknown Indian instrument"):
        normalizer.normalize(_record())
