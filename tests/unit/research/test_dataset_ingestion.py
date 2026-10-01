"""Tests for the deterministic registered-dataset ingestion workflow."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Candle
from quantx.ports.market_data import MarketDataPort, MarketDataStore
from quantx.research.data_quality import CompletenessStatus, DataQualityStatus
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_catalog import DatasetCatalog, InMemoryDatasetCatalog
from quantx.research.dataset_ingestion import HistoricalDatasetIngestionService

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

INSTRUMENT = InstrumentId("NSE", "TCS")


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=INSTRUMENT,
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _candle(timestamp: datetime = T0, **overrides) -> Candle:
    values = {
        "instrument": INSTRUMENT,
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


def _version(source_id: str = "dhan", version: str = "2026-01") -> DatasetVersion:
    return DatasetVersion(
        identity=DatasetIdentity(
            dataset_id="nse-equities",
            version=version,
            source_id=source_id,
            schema_version="1",
            content_fingerprint=fingerprint_bytes(b"declared-dataset"),
            metadata={"market": "NSE"},
        )
    )


class _FakeMarketDataPort:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self.candle_values = candles
        self.calls: list[tuple] = []

    def quote(self, instrument):
        raise AssertionError("quote is out of scope")

    def candles(self, instrument, *, timeframe, start, end):
        self.calls.append((instrument, timeframe, start, end))
        return self.candle_values

    def subscribe(self, instruments) -> None:
        raise AssertionError("subscribe is out of scope")

    def unsubscribe(self, instruments) -> None:
        raise AssertionError("unsubscribe is out of scope")


class _FakeStore:
    def __init__(self, inserted: int = 0) -> None:
        self.inserted = inserted
        self.calls: list[tuple] = []

    def save_candles(self, candles, *, source_id, dataset_version=""):
        self.calls.append((tuple(candles), source_id, dataset_version))
        return self.inserted

    def get_candles(self, *args, **kwargs):
        raise AssertionError("reads are out of scope")

    def save_quotes(self, *args, **kwargs):
        raise AssertionError("quotes are out of scope")

    def get_quotes(self, *args, **kwargs):
        raise AssertionError("quotes are out of scope")


def _service(
    candles: tuple[Candle, ...], inserted: int = 0
) -> tuple[HistoricalDatasetIngestionService, _FakeMarketDataPort, _FakeStore]:
    catalog: DatasetCatalog = InMemoryDatasetCatalog()
    catalog.register(_version())
    market_data = _FakeMarketDataPort(candles)
    store = _FakeStore(inserted=inserted)
    return (
        HistoricalDatasetIngestionService(
            catalog=catalog,
            market_data=market_data,
            store=store,
        ),
        market_data,
        store,
    )


def test_ingestion_reads_once_assesses_batch_and_persists_once() -> None:
    service, market_data, store = _service((_candle(T0), _candle(T1)), inserted=2)

    result = service.ingest(
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
    assert result.dataset_id == "nse-equities"
    assert result.version == "2026-01"
    assert result.source_id == "dhan"
    assert result.inserted_count == 2
    assert result.quality.quality is DataQualityStatus.VALID
    assert result.quality.completeness is CompletenessStatus.COMPLETE
    assert result.quality.observation_count == 2


def test_missing_expected_timestamp_is_reported_without_fabrication() -> None:
    service, _, store = _service((_candle(T0),))

    result = service.ingest(
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
    assert store.calls[0][0] == (_candle(T0),)


def test_unregistered_dataset_fails_before_market_data_access() -> None:
    market_data = _FakeMarketDataPort((_candle(),))
    store = _FakeStore()
    service = HistoricalDatasetIngestionService(
        catalog=InMemoryDatasetCatalog(),
        market_data=market_data,
        store=store,
    )

    with pytest.raises(ValueError, match="not registered"):
        service.ingest(
            dataset_id="nse-equities",
            version="missing",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
        )

    assert market_data.calls == []
    assert store.calls == []


@pytest.mark.parametrize(
    ("bad_candle", "message"),
    (
        (
            Candle(
                instrument=InstrumentId("NSE", "INFY"),
                timeframe="1m",
                timestamp=T0,
                open=Decimal("99"),
                high=Decimal("101"),
                low=Decimal("98"),
                close=Decimal("100"),
                volume=Decimal("1000"),
            ),
            "different instrument",
        ),
        (
            Candle(
                instrument=INSTRUMENT,
                timeframe="5m",
                timestamp=T0,
                open=Decimal("99"),
                high=Decimal("101"),
                low=Decimal("98"),
                close=Decimal("100"),
                volume=Decimal("1000"),
            ),
            "different timeframe",
        ),
        (
            Candle(
                instrument=INSTRUMENT,
                timeframe="1m",
                timestamp=datetime(2026, 1, 1, 9, 14, tzinfo=UTC),
                open=Decimal("99"),
                high=Decimal("101"),
                low=Decimal("98"),
                close=Decimal("100"),
                volume=Decimal("1000"),
            ),
            "outside the requested range",
        ),
    ),
)
def test_invalid_market_data_is_rejected_before_store(bad_candle, message) -> None:
    service, _, store = _service((bad_candle,))

    with pytest.raises(ValueError, match=message):
        service.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T2,
        )

    assert store.calls == []


def test_unknown_quality_without_expectations_remains_explicit() -> None:
    service, _, _ = _service((_candle(T0),))

    result = service.ingest(
        dataset_id="nse-equities",
        version="2026-01",
        instrument=INSTRUMENT,
        timeframe="1m",
        start=T0,
        end=T0,
    )

    assert result.quality.completeness is CompletenessStatus.UNKNOWN
    assert result.quality.quality is DataQualityStatus.VALID_WITH_WARNINGS


def test_dhan_adapter_composes_with_filesystem_catalog_and_sqlite_store(tmp_path) -> None:
    from quantx.persistence.sqlite import SqliteDatabase
    from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
    from quantx.plugins.dhan import DhanInstrumentRef, DhanMarketDataAdapter, InMemoryDhanTransport
    from quantx.plugins.dhan.models import DhanCandleSnapshot
    from quantx.research.dataset_catalog import FilesystemDatasetCatalog

    candles = (
        DhanCandleSnapshot(
            timeframe="1m",
            timestamp=T0,
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ),
        DhanCandleSnapshot(
            timeframe="1m",
            timestamp=T1,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("1100"),
        ),
    )
    instrument = _instrument()
    market_data = DhanMarketDataAdapter(
        _instruments={
            INSTRUMENT: (
                instrument,
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=InMemoryDhanTransport(
            candle_snapshots={("1333", "NSE_EQ"): candles}
        ),
    )
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    catalog.register(_version(source_id="dhan", version="2026-01"))
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteMarketDataStore(database)
        result = HistoricalDatasetIngestionService(
            catalog=catalog,
            market_data=market_data,
            store=store,
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

    assert result.inserted_count == 2
    assert result.quality.quality is DataQualityStatus.VALID
    assert result.quality.completeness is CompletenessStatus.COMPLETE
    assert retrieved == (
        Candle(
            instrument=INSTRUMENT,
            timeframe="1m",
            timestamp=T0,
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ),
        Candle(
            instrument=INSTRUMENT,
            timeframe="1m",
            timestamp=T1,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("1100"),
        ),
    )


def test_store_failure_propagates_after_single_read() -> None:
    class FailingStore(_FakeStore):
        def save_candles(self, candles, *, source_id, dataset_version=""):
            self.calls.append((tuple(candles), source_id, dataset_version))
            raise RuntimeError("store unavailable")

    catalog: DatasetCatalog = InMemoryDatasetCatalog()
    catalog.register(_version())
    market_data = _FakeMarketDataPort((_candle(),))
    store = FailingStore()
    service = HistoricalDatasetIngestionService(
        catalog=catalog,
        market_data=market_data,
        store=store,
    )

    with pytest.raises(RuntimeError, match="store unavailable"):
        service.ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T0,
        )

    assert len(market_data.calls) == 1
    assert len(store.calls) == 1
