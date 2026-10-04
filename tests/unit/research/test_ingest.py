from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.market_data import Candle
from quantx.research.data import HistoricalDataSeries
from quantx.research.ingest import CanonicalOHLCVNormalizer, RawMarketRecord, ingest_source


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
