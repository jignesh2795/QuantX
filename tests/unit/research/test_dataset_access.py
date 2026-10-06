"""Tests for the dataset-backed historical research access seam."""

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantx.domain.instruments import InstrumentId
from quantx.domain.market_data import Candle
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.ports.market_data import MarketDataStore
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_access import read_candles, read_observations
from quantx.research.dataset_catalog import DatasetCatalog, InMemoryDatasetCatalog

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


def _version(
    dataset_id: str = "nse-eq",
    version: str = "v1",
    source_id: str = "dhan",
    content: bytes = b"ohlcv-bytes-v1",
) -> DatasetVersion:
    return DatasetVersion(
        identity=DatasetIdentity(
            dataset_id=dataset_id,
            version=version,
            source_id=source_id,
            schema_version="1",
            content_fingerprint=fingerprint_bytes(content),
            metadata={},
        )
    )


class FakeCatalog:
    """Scripted dataset catalog with lookup tracking."""

    def __init__(self, versions: tuple[DatasetVersion, ...] = ()) -> None:
        self._versions = {
            (version.identity.dataset_id, version.identity.version): version for version in versions
        }
        self.lookups: list = []
        self.error: Exception | None = None

    def register(self, dataset_version: DatasetVersion) -> DatasetVersion:
        raise AssertionError("registration is out of scope for dataset reads")

    def get(self, dataset_id: str, version: str) -> DatasetVersion | None:
        self.lookups.append((dataset_id, version))
        if self.error is not None:
            raise self.error
        return self._versions.get((dataset_id, version))


class FakeStore:
    """Scripted market-data store with query tracking."""

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles
        self.queries: list = []
        self.error: Exception | None = None

    def save_candles(self, candles, *, source_id, dataset_version=""):
        raise AssertionError("writes are out of scope for dataset reads")

    def save_quotes(self, quotes, *, source_id, dataset_version=""):
        raise AssertionError("writes are out of scope for dataset reads")

    def get_candles(
        self,
        instrument,
        *,
        timeframe,
        start,
        end,
        source_id=None,
        dataset_version=None,
    ):
        self.queries.append(
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "source_id": source_id,
                "dataset_version": dataset_version,
            }
        )
        if self.error is not None:
            raise self.error
        return self._candles

    def get_quotes(self, instrument, **kwargs):
        raise AssertionError("quotes are out of scope for candle reads")


def _read(catalog, store, **overrides):
    arguments = {
        "catalog": catalog,
        "store": store,
        "dataset_id": "nse-eq",
        "version": "v1",
        "instrument": TCS,
        "timeframe": "1m",
        "start": T0,
        "end": T1,
    }
    arguments.update(overrides)
    return read_candles(**arguments)


def test_registered_dataset_resolves_successfully() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore((_candle(T0), _candle(T1)))

    assert _read(catalog, store) == (_candle(T0), _candle(T1))


def test_catalog_lookup_receives_exact_identity() -> None:
    catalog = FakeCatalog((_version(),))

    _read(catalog, FakeStore(), dataset_id="nse-eq", version="v1")

    assert catalog.lookups == [("nse-eq", "v1")]


def test_registered_source_id_forwarded_exactly() -> None:
    catalog = FakeCatalog((_version(source_id="csv-import"),))
    store = FakeStore()

    _read(catalog, store)

    assert store.queries[0]["source_id"] == "csv-import"


def test_registered_version_forwarded_as_dataset_version() -> None:
    catalog = FakeCatalog((_version(version="v2"),))
    store = FakeStore()

    _read(catalog, store, version="v2")

    assert store.queries[0]["dataset_version"] == "v2"


def test_caller_instrument_forwarded_unchanged() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    _read(catalog, store)

    assert store.queries[0]["instrument"] == TCS
    assert store.queries[0]["instrument"] is TCS


def test_timeframe_forwarded_unchanged() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    _read(catalog, store, timeframe="5m")

    assert store.queries[0]["timeframe"] == "5m"


def test_exact_bounds_forwarded() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    _read(catalog, store, start=T0, end=T2)

    assert store.queries[0]["start"] == T0
    assert store.queries[0]["end"] == T2


def test_returned_candles_unchanged() -> None:
    candles = (_candle(T0), _candle(T1))
    catalog = FakeCatalog((_version(),))

    assert _read(catalog, FakeStore(candles)) == candles


def test_empty_registered_result_returns_empty_tuple() -> None:
    catalog = FakeCatalog((_version(),))

    assert _read(catalog, FakeStore(())) == ()


def test_missing_dataset_raises_explicit_error() -> None:
    catalog = FakeCatalog(())
    store = FakeStore((_candle(),))

    with pytest.raises(ValueError, match="not registered"):
        _read(catalog, store)


def test_missing_dataset_does_not_call_store() -> None:
    catalog = FakeCatalog(())
    store = FakeStore((_candle(),))

    with pytest.raises(ValueError, match="not registered"):
        _read(catalog, store)

    assert store.queries == []


def test_empty_timeframe_rejected() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    with pytest.raises(ValueError, match="timeframe"):
        _read(catalog, store, timeframe="  ")

    assert store.queries == []


def test_naive_start_rejected() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    with pytest.raises(ValueError, match="timezone-aware"):
        _read(catalog, store, start=datetime(2026, 1, 1, 9, 15))

    assert store.queries == []


def test_naive_end_rejected() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    with pytest.raises(ValueError, match="timezone-aware"):
        _read(catalog, store, end=datetime(2026, 1, 1, 9, 16))

    assert store.queries == []


def test_end_before_start_rejected() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()

    with pytest.raises(ValueError, match="must not precede start"):
        _read(catalog, store, start=T1, end=T0)

    assert store.queries == []


def test_catalog_exception_propagates() -> None:
    catalog = FakeCatalog((_version(),))
    catalog.error = RuntimeError("catalog unavailable")
    store = FakeStore()

    with pytest.raises(RuntimeError, match="catalog unavailable"):
        _read(catalog, store)

    assert store.queries == []


def test_store_exception_propagates() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore()
    store.error = RuntimeError("store unavailable")

    with pytest.raises(RuntimeError, match="store unavailable"):
        _read(catalog, store)


def test_no_fingerprint_used_as_query_key() -> None:
    version = _version(content=b"distinct-content-fingerprint")
    catalog = FakeCatalog((version,))
    store = FakeStore()

    _read(catalog, store)

    query = store.queries[0]
    assert query["source_id"] == "dhan"
    assert query["dataset_version"] == "v1"
    assert version.identity.content_fingerprint not in {
        str(query["source_id"]),
        str(query["dataset_version"]),
    }


def test_no_caller_source_id_injection_point_exists() -> None:
    import inspect

    from quantx.research import dataset_access

    parameters = inspect.signature(dataset_access.read_candles).parameters

    assert "source_id" not in parameters
    assert "dataset_version" not in parameters


def test_protocol_and_vendor_neutrality() -> None:
    assert isinstance(FakeCatalog(()), DatasetCatalog)
    assert isinstance(FakeStore(()), MarketDataStore)


def test_catalog_lookup_precedes_store_read() -> None:
    events: list = []

    class SequencedCatalog(FakeCatalog):
        def get(self, dataset_id: str, version: str):
            events.append("catalog.get")
            return super().get(dataset_id, version)

    class SequencedStore(FakeStore):
        def get_candles(self, instrument, **kwargs):
            events.append("store.get_candles")
            return super().get_candles(instrument, **kwargs)

    _read(SequencedCatalog((_version(),)), SequencedStore((_candle(),)))

    assert events == ["catalog.get", "store.get_candles"]


def test_no_float_conversion_in_returned_values() -> None:
    candles = (
        _candle(
            open=Decimal("0.1"),
            high=Decimal("0.100000000000000001"),
            low=Decimal("0.1"),
            close=Decimal("0.100000000000000001"),
        ),
    )
    catalog = FakeCatalog((_version(),))

    (retrieved,) = _read(catalog, FakeStore(candles))

    assert str(retrieved.open) == "0.1"
    assert str(retrieved.close) == "0.100000000000000001"


def test_no_network_or_sdk_imports() -> None:
    import quantx.research.dataset_access as module

    assert "dhan" not in module.__name__
    assert "broker" not in module.__name__


def test_registered_version_unmutated() -> None:
    version = _version()
    snapshot = _version()
    catalog = FakeCatalog((version,))

    _read(catalog, FakeStore((_candle(),)))

    assert version == snapshot


def test_sqlite_backed_version_scoped_reads() -> None:
    first = _version(dataset_id="nse-eq", version="v1", source_id="dhan", content=b"v1-bytes")
    second = _version(
        dataset_id="nse-eq", version="v2", source_id="csv-import", content=b"v2-bytes"
    )
    catalog = InMemoryDatasetCatalog()
    catalog.register(first)
    catalog.register(second)

    with tempfile.TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "quantx.db")
        try:
            store = SqliteMarketDataStore(database)
            store.save_candles(
                (_candle(T0), _candle(T1)),
                source_id="dhan",
                dataset_version="v1",
            )
            store.save_candles(
                (_candle(T2, high=Decimal("103"), close=Decimal("102")),),
                source_id="csv-import",
                dataset_version="v2",
            )

            first_read = read_candles(
                catalog=catalog,
                store=store,
                dataset_id="nse-eq",
                version="v1",
                instrument=TCS,
                timeframe="1m",
                start=T0,
                end=T2,
            )
            second_read = read_candles(
                catalog=catalog,
                store=store,
                dataset_id="nse-eq",
                version="v2",
                instrument=TCS,
                timeframe="1m",
                start=T0,
                end=T2,
            )
        finally:
            database.close()

    assert [candle.timestamp for candle in first_read] == [T0, T1]
    assert [candle.timestamp for candle in second_read] == [T2]
    assert second_read[0].close == Decimal("102")


def test_read_observations_propagates_dataset_identity() -> None:
    catalog = FakeCatalog((_version(),))
    store = FakeStore((_candle(T0), _candle(T1)))
    observations = read_observations(
        catalog=catalog,
        store=store,
        dataset_id="nse-eq",
        version="v1",
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T1,
    )

    assert len(observations) == 2
    for observation in observations:
        assert observation.dataset_id == "nse-eq"
        assert observation.source_id == "dhan"
        assert observation.dataset_version == "v1"
