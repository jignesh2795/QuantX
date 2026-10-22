from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.research.data import HistoricalDataSeries
from quantx.research.ingest import (
    CanonicalOHLCVNormalizer,
    CatalogOHLCVNormalizer,
    RawMarketRecord,
    ingest_source,
)
from quantx.research.replay import HistoricalReplay


class Source:
    def __init__(self, records):
        self._records = records

    def read(self):
        return iter(self._records)


def _record() -> RawMarketRecord:
    return RawMarketRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        instrument="BTC/USDT",
        sequence=1,
        fields={
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1234.5,
        },
        timeframe="5m",
    )


def test_normalizes_ohlcv_as_lossless_candle() -> None:
    series = ingest_source(
        Source([_record()]),
        CanonicalOHLCVNormalizer("dataset", "v1"),
    )

    assert isinstance(series, HistoricalDataSeries)
    observation = tuple(series)[0]
    assert isinstance(observation.snapshot, Candle)
    assert observation.snapshot.instrument == observation.instrument
    assert observation.snapshot.timeframe == "5m"
    assert observation.snapshot.open == Decimal("100")
    assert observation.snapshot.high == Decimal("110")
    assert observation.snapshot.low == Decimal("95")
    assert observation.snapshot.close == Decimal("105")
    assert observation.snapshot.volume == Decimal("1234.5")
    assert observation.source_id == "dataset"
    assert observation.dataset_version == "v1"


def test_missing_required_ohlcv_field_is_rejected() -> None:
    record = RawMarketRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        instrument="BTC/USDT",
        sequence=1,
        fields={
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
        },
        timeframe="5m",
    )
    with pytest.raises(ValueError, match="missing required historical fields"):
        CanonicalOHLCVNormalizer("dataset", "v1").normalize(record)


def test_missing_timeframe_is_rejected_without_a_default() -> None:
    with pytest.raises(TypeError):
        RawMarketRecord(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            instrument="BTC/USDT",
            sequence=1,
            fields={
                "open": 100,
                "high": 110,
                "low": 95,
                "close": 105,
                "volume": 1234.5,
            },
        )


def test_calendar_classification_does_not_change_candle_payload() -> None:
    class Calendar:
        def classify(self, timestamp):
            return timestamp

    observation = CanonicalOHLCVNormalizer(
        "dataset",
        "v1",
        calendar=Calendar(),
    ).normalize(_record())

    assert observation.snapshot == Candle(
        instrument=observation.snapshot.instrument,
        timeframe="5m",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("1234.5"),
    )


class _Registry:
    def __init__(self, instruments: tuple[Instrument, ...] = ()) -> None:
        self._instruments = {instrument.instrument_id: instrument for instrument in instruments}

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instruments.get(instrument_id)


def _catalog_instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _catalog_normalizer(*instruments: Instrument) -> CatalogOHLCVNormalizer:
    return CatalogOHLCVNormalizer(
        registry=_Registry(instruments),
        instrument_id=InstrumentId("NSE", "TCS"),
        dataset_id="nse-fixture",
        dataset_version="v1",
    )


def _catalog_record(instrument: str = "TCS") -> RawMarketRecord:
    return RawMarketRecord(
        timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=UTC),
        instrument=instrument,
        sequence=0,
        fields={
            "open": Decimal("100.100000000000000001"),
            "high": Decimal("101.00000000000001"),
            "low": Decimal("99.09799999999999999"),
            "close": Decimal("100.00000000000001"),
            "volume": Decimal("25000"),
        },
        timeframe="5m",
    )


def test_catalog_normalizer_preserves_decimal_payload_and_identity() -> None:
    observation = _catalog_normalizer(_catalog_instrument()).normalize(_catalog_record())

    assert observation.instrument == InstrumentId("NSE", "TCS")
    assert isinstance(observation.snapshot, Candle)
    assert observation.snapshot.instrument == InstrumentId("NSE", "TCS")
    assert observation.snapshot.timeframe == "5m"
    assert observation.snapshot.open == Decimal("100.100000000000000001")
    assert observation.snapshot.high == Decimal("101.00000000000001")
    assert observation.snapshot.low == Decimal("99.09799999999999999")
    assert observation.snapshot.close == Decimal("100.00000000000001")
    assert observation.snapshot.volume == Decimal("25000")
    assert observation.source_id == "nse-fixture"
    assert observation.dataset_version == "v1"
    assert observation.sequence == 0

    series = HistoricalDataSeries((observation,))
    assert HistoricalReplay(series).run(lambda _frame: None) == 1


def test_catalog_normalizer_rejects_symbol_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        _catalog_normalizer(_catalog_instrument()).normalize(_catalog_record("INFY"))


def test_catalog_normalizer_fails_closed_for_unknown_instrument() -> None:
    with pytest.raises(ValueError, match="unknown instrument"):
        _catalog_normalizer().normalize(_catalog_record())
