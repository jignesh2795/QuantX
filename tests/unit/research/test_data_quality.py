"""Tests for the deterministic historical candle quality seam."""

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from quantx.domain.instruments import InstrumentId
from quantx.domain.market_data import Candle
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.research.data_quality import (
    CompletenessStatus,
    DataQualityStatus,
    HistoricalDataQuality,
    assess_candles,
)
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_access import read_candles
from quantx.research.dataset_catalog import InMemoryDatasetCatalog

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

TCS = InstrumentId("NSE", "TCS")


def _candle(timestamp: datetime = T0, **overrides) -> Candle:
    values = {
        "instrument": TCS,
        "timeframe": "1m",
        "timestamp": timestamp,
        "open": Decimal("99"),
        "high": Decimal("101"),
        "low": Decimal("98"),
        "close": Decimal("100"),
        "volume": Decimal("1000"),
    }
    values.update(overrides)
    return Candle(**values)


def test_exact_complete_collection() -> None:
    result = assess_candles((_candle(T0), _candle(T1)), (T0, T1))

    assert isinstance(result, HistoricalDataQuality)
    assert result.quality is DataQualityStatus.VALID
    assert result.completeness is CompletenessStatus.COMPLETE
    assert result.observation_count == 2
    assert result.expected_count == 2
    assert result.missing_timestamps == ()
    assert result.unexpected_timestamps == ()
    assert result.duplicate_timestamps == ()
    assert result.out_of_order is False
    assert result.issues == ()


def test_missing_expected_timestamp() -> None:
    result = assess_candles((_candle(T0),), (T0, T1))

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.INCOMPLETE
    assert result.missing_timestamps == (T1,)
    assert result.unexpected_timestamps == ()
    assert any(
        issue.message == "expected timestamp is missing from observations"
        for issue in result.issues
    )


def test_unexpected_observed_timestamp() -> None:
    result = assess_candles((_candle(T0), _candle(T2)), (T0, T1))

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.INCOMPLETE
    assert result.missing_timestamps == (T1,)
    assert result.unexpected_timestamps == (T2,)
    assert any(
        issue.message == "observed timestamp was not in expected set"
        for issue in result.issues
    )


def test_duplicate_timestamp() -> None:
    result = assess_candles((_candle(T0), _candle(T0), _candle(T1)), (T0, T1))

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.COMPLETE
    assert result.duplicate_timestamps == (T0,)
    assert any(
        issue.message == "duplicate observation timestamp" for issue in result.issues
    )


def test_out_of_order_observation() -> None:
    result = assess_candles((_candle(T1), _candle(T0)), (T0, T1))

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.out_of_order is True
    assert any(issue.message == "observations are not chronologically ordered" for issue in result.issues)


def test_missing_and_unexpected_together() -> None:
    result = assess_candles((_candle(T2),), (T0, T1))

    assert result.missing_timestamps == (T0, T1)
    assert result.unexpected_timestamps == (T2,)
    assert result.completeness is CompletenessStatus.INCOMPLETE


def test_no_expected_timestamps_completeness_unknown() -> None:
    result = assess_candles((_candle(T0), _candle(T1)))

    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.expected_count is None
    assert result.quality is not DataQualityStatus.VALID
    assert result.completeness is not CompletenessStatus.COMPLETE


def test_clean_data_without_expectations_warns() -> None:
    result = assess_candles((_candle(T0), _candle(T1)))

    assert result.quality is DataQualityStatus.VALID_WITH_WARNINGS
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.issues == ()


def test_empty_data_without_expectations() -> None:
    result = assess_candles(())

    assert result.quality is DataQualityStatus.VALID_WITH_WARNINGS
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.observation_count == 0


def test_empty_data_with_expectations_incomplete() -> None:
    result = assess_candles((), (T0,))

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.INCOMPLETE
    assert result.missing_timestamps == (T0,)


def test_naive_observed_timestamp_rejected() -> None:
    class NaiveCandle:
        timestamp = datetime(2026, 1, 1, 9, 15)

    result = assess_candles((NaiveCandle(),))  # type: ignore[arg-type]

    assert result.quality is DataQualityStatus.REJECTED
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.observation_count == 1


def test_naive_expected_timestamp_rejected() -> None:
    result = assess_candles((_candle(T0),), (datetime(2026, 1, 1, 9, 15),))

    assert result.quality is DataQualityStatus.REJECTED
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.expected_count == 1
    assert tuple(issue.message for issue in result.issues) == (
        "expected timestamp must be timezone-aware",
    )


def test_timezone_equivalent_instants_compare_equal() -> None:
    ist = ZoneInfo("Asia/Kolkata")
    same_instant = datetime(2026, 1, 1, 14, 45, tzinfo=ist)

    assert same_instant == T0
    result = assess_candles((_candle(T0),), (same_instant,))

    assert result.quality is DataQualityStatus.VALID
    assert result.completeness is CompletenessStatus.COMPLETE
    assert result.missing_timestamps == ()
    assert result.unexpected_timestamps == ()


def test_expected_ordering_does_not_matter() -> None:
    first = assess_candles((_candle(T0), _candle(T1)), (T1, T0))
    second = assess_candles((_candle(T0), _candle(T1)), (T0, T1))

    assert first == second


def test_issue_ordering_deterministic() -> None:
    first = assess_candles((_candle(T1), _candle(T1), _candle(T2)), (T0,))
    second = assess_candles((_candle(T1), _candle(T1), _candle(T2)), (T0,))

    assert first.issues == second.issues
    assert tuple(issue.message for issue in first.issues) == (
        "duplicate observation timestamp",
        "expected timestamp is missing from observations",
        "observed timestamp was not in expected set",
        "observed timestamp was not in expected set",
    )


def test_canonical_values_not_mutated() -> None:
    candles = (_candle(T0), _candle(T1))
    snapshot = tuple(
        (candle.timestamp, candle.open, candle.close, candle.volume) for candle in candles
    )

    assess_candles(candles, (T0, T1))

    assert (
        tuple((candle.timestamp, candle.open, candle.close, candle.volume) for candle in candles)
        == snapshot
    )


def test_analyzer_does_not_sort_input() -> None:
    result = assess_candles((_candle(T1), _candle(T0)), (T0, T1))

    assert result.out_of_order is True


def test_analyzer_does_not_fabricate_data() -> None:
    result = assess_candles((_candle(T0),), (T0, T1))

    assert result.observation_count == 1
    assert result.missing_timestamps == (T1,)
    assert result.completeness is CompletenessStatus.INCOMPLETE


def test_non_candle_input_rejected_explicitly() -> None:
    result = assess_candles(("not-a-candle",))  # type: ignore[arg-type]

    assert result.quality is DataQualityStatus.REJECTED
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.observation_count == 1
    assert tuple(issue.message for issue in result.issues) == (
        "observations must be canonical historical observations",
    )


def test_quality_classification_deterministic() -> None:
    first = assess_candles((_candle(T0),), (T0, T1))
    second = assess_candles((_candle(T0),), (T0, T1))

    assert first == second


def test_duplicate_timestamps_remain_visible() -> None:
    result = assess_candles((_candle(T0), _candle(T0)), (T0,))

    assert result.duplicate_timestamps == (T0,)
    assert result.observation_count == 2


def test_no_float_conversion() -> None:
    candle = _candle(
        open=Decimal("0.1"),
        high=Decimal("0.100000000000000001"),
        low=Decimal("0.1"),
        close=Decimal("0.100000000000000001"),
    )
    result = assess_candles((candle,), (T0,))

    assert result.quality is DataQualityStatus.VALID
    assert str(candle.open) == "0.1"
    assert str(candle.close) == "0.100000000000000001"


def test_no_filesystem_network_broker_imports() -> None:
    import quantx.research.data_quality as module

    source = Path(module.__file__).read_text()
    lowered = source.lower()
    for marker in ("dhan", "broker", "socket", "requests", "urlopen", "dhanhq", "sqlite"):
        assert marker not in lowered, marker


def test_protocol_and_vendor_neutrality() -> None:
    import quantx.research.data_quality as compatibility
    import quantx.research.quality as canonical

    assert compatibility.assess_candles is canonical.assess_candles
    assert compatibility.HistoricalDataQuality is canonical.HistoricalDataQuality
    assert compatibility.HistoricalDataQualityGate is canonical.HistoricalDataQualityGate


def test_dataset_access_integration() -> None:
    version = DatasetVersion(
        identity=DatasetIdentity(
            dataset_id="nse-eq",
            version="v1",
            source_id="dhan",
            schema_version="1",
            content_fingerprint=fingerprint_bytes(b"v1-bytes"),
            metadata={},
        )
    )
    catalog = InMemoryDatasetCatalog()
    catalog.register(version)

    with tempfile.TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "quantx.db")
        try:
            store = SqliteMarketDataStore(database)
            store.save_candles((_candle(T0), _candle(T1)), source_id="dhan", dataset_version="v1")
            retrieved = read_candles(
                catalog=catalog,
                store=store,
                dataset_id="nse-eq",
                version="v1",
                instrument=TCS,
                timeframe="1m",
                start=T0,
                end=T1,
            )
        finally:
            database.close()

    result = assess_candles(retrieved, (T0, T1))

    assert result.quality is DataQualityStatus.VALID
    assert result.completeness is CompletenessStatus.COMPLETE
