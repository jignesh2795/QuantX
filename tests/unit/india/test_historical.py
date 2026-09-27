from datetime import UTC, datetime

import pytest

from quantx.domain.enums import AssetClass
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


def test_indian_normalizer_uses_catalog_identity_and_replays() -> None:
    normalizer = _normalizer()
    observation = normalizer.normalize(
        RawMarketRecord(
            timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=UTC),
            instrument="TCS",
            sequence=0,
            fields={"open": 100, "high": 101, "low": 99, "close": 100.5},
        )
    )

    assert observation.instrument == InstrumentId("NSE", "TCS")
    assert observation.snapshot.last is not None
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
                fields={"open": 100, "high": 101, "low": 99, "close": 100.5},
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
        normalizer.normalize(
            RawMarketRecord(
                timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=UTC),
                instrument="TCS",
                sequence=0,
                fields={"open": 100, "high": 101, "low": 99, "close": 100.5},
            )
        )
