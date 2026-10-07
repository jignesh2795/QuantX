"""Tests for the R1-C14 historical dataset ingestion application boundary."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.dataset_ingestion import HistoricalDatasetIngestionService
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.research.data_quality import CompletenessStatus, DataQualityStatus
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_catalog import InMemoryDatasetCatalog

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
INSTRUMENT = InstrumentId("NSE", "TCS")


def candle(timestamp=T0, *, instrument=INSTRUMENT, timeframe="1m"):
    return Candle(
        instrument=instrument,
        timeframe=timeframe,
        timestamp=timestamp,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("1000"),
    )


class FakeMarketData:
    def __init__(self, values=()):
        self.values = tuple(values)
        self.calls = []

    def quote(self, instrument):
        raise AssertionError("quote is outside C14.2 scope")

    def candles(self, instrument, *, timeframe, start, end):
        self.calls.append((instrument, timeframe, start, end))
        return self.values

    def subscribe(self, instruments):
        raise AssertionError("subscribe is outside C14.2 scope")

    def unsubscribe(self, instruments):
        raise AssertionError("unsubscribe is outside C14.2 scope")


class FakeStore:
    def __init__(self, inserted=0):
        self.inserted = inserted
        self.calls = []

    def save_candles(self, candles, *, source_id, dataset_version=""):
        self.calls.append((tuple(candles), source_id, dataset_version))
        return self.inserted

    def get_candles(self, *args, **kwargs):
        raise AssertionError("reads are outside C14.2 scope")

    def save_quotes(self, *args, **kwargs):
        raise AssertionError("quotes are outside C14.2 scope")

    def get_quotes(self, *args, **kwargs):
        raise AssertionError("quotes are outside C14.2 scope")


def service(values=(), inserted=0):
    catalog = InMemoryDatasetCatalog()
    catalog.register(
        DatasetVersion(
            identity=DatasetIdentity(
                dataset_id="nse-equities",
                version="2026-01",
                source_id="dhan",
                schema_version="1",
                content_fingerprint=fingerprint_bytes(b"declared"),
                metadata={},
            )
        )
    )
    market_data = FakeMarketData(values)
    store = FakeStore(inserted)
    return HistoricalDatasetIngestionService(
        catalog=catalog,
        market_data=market_data,
        store=store,
    ), market_data, store


def test_registered_dataset_is_retrieved_assessed_and_persisted_once():
    svc, market_data, store = service((candle(T0), candle(T1)), inserted=2)

    result = svc.ingest(
        dataset_id="nse-equities",
        version="2026-01",
        instrument=INSTRUMENT,
        timeframe="1m",
        start=T0,
        end=T1,
        expected_timestamps=(T0, T1),
    )

    assert len(market_data.calls) == 1
    assert len(store.calls) == 1
    assert store.calls[0][1:] == ("dhan", "2026-01")
    assert result.dataset_version.identity.dataset_id == "nse-equities"
    assert result.dataset_version.identity.version == "2026-01"
    assert result.dataset_version.identity.source_id == "dhan"
    assert result.inserted_count == 2
    assert result.quality.quality is DataQualityStatus.VALID
    assert result.quality.completeness is CompletenessStatus.COMPLETE


def test_missing_expected_timestamp_is_evidence_not_fabrication():
    svc, _, store = service((candle(T0),))

    result = svc.ingest(
        dataset_id="nse-equities",
        version="2026-01",
        instrument=INSTRUMENT,
        timeframe="1m",
        start=T0,
        end=T1,
        expected_timestamps=(T0, T1),
    )

    assert result.quality.completeness is CompletenessStatus.INCOMPLETE
    assert result.quality.missing_timestamps == (T1,)
    assert store.calls[0][0] == (candle(T0),)


def test_without_expected_timestamps_completeness_is_unknown():
    svc, _, _ = service((candle(T0),))

    result = svc.ingest(
        dataset_id="nse-equities",
        version="2026-01",
        instrument=INSTRUMENT,
        timeframe="1m",
        start=T0,
        end=T0,
    )

    assert result.quality.completeness is CompletenessStatus.UNKNOWN
    assert result.quality.quality is DataQualityStatus.VALID_WITH_WARNINGS


def test_unregistered_dataset_fails_before_provider_and_store():
    catalog = InMemoryDatasetCatalog()
    market_data = FakeMarketData((candle(),))
    store = FakeStore()
    svc = HistoricalDatasetIngestionService(
        catalog=catalog,
        market_data=market_data,
        store=store,
    )

    with pytest.raises(ValueError, match="not registered"):
        svc.ingest(
            dataset_id="missing",
            version="1",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
        )

    assert market_data.calls == []
    assert store.calls == []


@pytest.mark.parametrize(
    ("start", "end", "timeframe", "message"),
    (
        (datetime(2026, 1, 1, 9, 15), T0, "1m", "start must be timezone-aware"),
        (T1, T0, "1m", "end must not precede start"),
        (T0, T0, " ", "timeframe must not be empty"),
    ),
)
def test_request_validation_happens_before_provider(start, end, timeframe, message):
    svc, market_data, store = service()

    with pytest.raises(ValueError, match=message):
        svc.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    assert market_data.calls == []
    assert store.calls == []


@pytest.mark.parametrize(
    ("value", "message"),
    (
        (object(), "non-canonical candle"),
        (candle(instrument=InstrumentId("NSE", "INFY")), "different instrument"),
        (candle(timeframe="5m"), "different timeframe"),
        (candle(datetime(2026, 1, 1, 9, 14, tzinfo=UTC)), "outside the requested range"),
    ),
)
def test_invalid_provider_output_fails_before_persistence(value, message):
    svc, _, store = service((value,))

    with pytest.raises(ValueError, match=message):
        svc.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
        )

    assert store.calls == []


def test_rejected_quality_fails_closed_before_persistence():
    svc, _, store = service((candle(),))
    naive_expected = (datetime(2026, 1, 1, 9, 15),)

    with pytest.raises(ValueError, match="quality rejected"):
        svc.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
            expected_timestamps=naive_expected,
        )

    assert store.calls == []


def test_empty_provider_result_is_not_failure():
    svc, market_data, store = service(())

    result = svc.ingest(
        dataset_id="nse-equities",
        version="2026-01",
        instrument=INSTRUMENT,
        timeframe="1m",
        start=T0,
        end=T0,
    )

    assert result.inserted_count == 0
    assert result.quality.observation_count == 0
    assert result.quality.completeness is CompletenessStatus.UNKNOWN
    assert market_data.calls
    assert store.calls == [((), "dhan", "2026-01")]


def test_provider_failure_propagates_and_store_is_not_touched():
    class FailingMarketData(FakeMarketData):
        def candles(self, instrument, *, timeframe, start, end):
            self.calls.append((instrument, timeframe, start, end))
            raise RuntimeError("provider unavailable")

    catalog = InMemoryDatasetCatalog()
    catalog.register(
        DatasetVersion(
            identity=DatasetIdentity(
                dataset_id="nse-equities",
                version="2026-01",
                source_id="dhan",
                schema_version="1",
                content_fingerprint=fingerprint_bytes(b"declared"),
            )
        )
    )
    market_data = FailingMarketData()
    store = FakeStore()
    svc = HistoricalDatasetIngestionService(
        catalog=catalog, market_data=market_data, store=store
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        svc.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
        )

    assert store.calls == []


def test_store_failure_propagates():
    class FailingStore(FakeStore):
        def save_candles(self, candles, *, source_id, dataset_version=""):
            self.calls.append((tuple(candles), source_id, dataset_version))
            raise RuntimeError("store unavailable")

    catalog = InMemoryDatasetCatalog()
    catalog.register(
        DatasetVersion(
            identity=DatasetIdentity(
                dataset_id="nse-equities",
                version="2026-01",
                source_id="dhan",
                schema_version="1",
                content_fingerprint=fingerprint_bytes(b"declared"),
            )
        )
    )
    market_data = FakeMarketData((candle(),))
    failing = FailingStore()
    svc = HistoricalDatasetIngestionService(
        catalog=catalog,
        market_data=market_data,
        store=failing,
    )

    with pytest.raises(RuntimeError, match="store unavailable"):
        svc.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
        )

    assert len(market_data.calls) == 1


def test_sqlite_store_preserves_dataset_binding_end_to_end(tmp_path):
    from quantx.persistence.sqlite import SqliteDatabase
    from quantx.persistence.sqlite.market_data import SqliteMarketDataStore

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteMarketDataStore(database)
        catalog = InMemoryDatasetCatalog()
        catalog.register(
            DatasetVersion(
                identity=DatasetIdentity(
                    dataset_id="nse-equities",
                    version="2026-01",
                    source_id="dhan",
                    schema_version="1",
                    content_fingerprint=fingerprint_bytes(b"declared"),
                )
            )
        )
        market_data = FakeMarketData((candle(T0), candle(T1)))
        result = HistoricalDatasetIngestionService(
            catalog=catalog, market_data=market_data, store=store
        ).ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
            expected_timestamps=(T0, T1),
        )
        retrieved = store.get_candles(
            INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
            source_id="dhan",
            dataset_version="2026-01",
        )
    finally:
        database.close()

    assert result.dataset_version.identity.dataset_id == "nse-equities"
    assert result.inserted_count == 2
    assert retrieved == (candle(T0), candle(T1))
