from datetime import datetime, timezone

import pytest

from quantx.research.data import HistoricalDataSeries
from quantx.research.ingest import CanonicalOHLCVNormalizer, RawMarketRecord, ingest_source


class Source:
    def __init__(self, records):
        self._records = records

    def read(self):
        return iter(self._records)


def test_normalizes_ohlcv_without_inventing_fields() -> None:
    record = RawMarketRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        instrument="BTC/USDT",
        sequence=1,
        fields={"open": 100, "high": 110, "low": 95, "close": 105},
    )
    series = ingest_source(
        Source([record]),
        CanonicalOHLCVNormalizer("dataset", "v1"),
    )
    assert isinstance(series, HistoricalDataSeries)
    observation = tuple(series)[0]
    assert observation.data["volume"] is None
    assert observation.source_id == "dataset"
    assert observation.dataset_version == "v1"


def test_missing_required_field_is_rejected() -> None:
    record = RawMarketRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        instrument="BTC/USDT",
        sequence=1,
        fields={"open": 100, "high": 110, "low": 95},
    )
    with pytest.raises(ValueError, match="missing required historical fields"):
        CanonicalOHLCVNormalizer("dataset", "v1").normalize(record)
