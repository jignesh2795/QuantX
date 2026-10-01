"""Tests for the canonical historical candle ingestion bridge."""

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantx.domain.instruments import InstrumentId
from quantx.domain.market_data import Candle
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.ports.market_data import MarketDataPort, MarketDataStore
from quantx.research.market_data_ingestion import ingest_historical_candles

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


class FakeMarketDataPort:
    """Vendor-neutral scripted market-data port with call tracking."""

    def __init__(self, candles: tuple[Candle, ...] = ()) -> None:
        self._candles = candles
        self.calls: list = []

    def quote(self, instrument):  # type: ignore[no-untyped-def]
        raise AssertionError("quote is out of scope for candle ingestion")

    def candles(self, instrument, *, timeframe, start, end):
        self.calls.append(("candles", instrument, timeframe, start, end))
        return self._candles

    def subscribe(self, instruments) -> None:
        raise AssertionError("subscribe is out of scope for candle ingestion")

    def unsubscribe(self, instruments) -> None:
        raise AssertionError("unsubscribe is out of scope for candle ingestion")


class FakeMarketDataStore:
    """Vendor-neutral scripted market-data store with call tracking."""

    def __init__(self, inserted: int = 0) -> None:
        self._inserted = inserted
        self.calls: list = []

    def save_candles(self, candles, *, source_id, dataset_version=""):
        self.calls.append(("save_candles", tuple(candles), source_id, dataset_version))
        return self._inserted

    def save_quotes(self, quotes, *, source_id, dataset_version=""):
        raise AssertionError("quotes are out of scope for candle ingestion")

    def get_candles(self, instrument, **kwargs):
        raise AssertionError("reads are out of scope for candle ingestion")

    def get_quotes(self, instrument, **kwargs):
        raise AssertionError("reads are out of scope for candle ingestion")


def test_retrieval_persisted_with_inserted_count() -> None:
    port = FakeMarketDataPort((_candle(T0), _candle(T1)))
    store = FakeMarketDataStore(inserted=2)

    assert (
        ingest_historical_candles(
            market_data=port,
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=T1,
            source_id="dhan",
            dataset_version="v1",
        )
        == 2
    )


def test_exact_candle_values_preserved() -> None:
    candles = (
        _candle(
            T0,
            open=Decimal("0.100000000000000001"),
            high=Decimal("0.100000000000000001"),
            low=Decimal("0.100000000000000001"),
            close=Decimal("0.100000000000000001"),
        ),
        _candle(T1, volume=Decimal("123456789.123456789")),
    )
    port = FakeMarketDataPort(candles)
    store = FakeMarketDataStore()

    ingest_historical_candles(
        market_data=port,
        store=store,
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T1,
        source_id="dhan",
    )

    (call,) = store.calls
    assert call[0] == "save_candles"
    assert call[1] == candles
    assert [str(candle.open) for candle in call[1]] == [
        "0.100000000000000001",
        "99",
    ]


def test_source_and_dataset_forwarded_exactly() -> None:
    port = FakeMarketDataPort((_candle(),))
    store = FakeMarketDataStore()

    ingest_historical_candles(
        market_data=port,
        store=store,
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T0,
        source_id="dhan",
        dataset_version="2026-01",
    )

    (call,) = store.calls
    assert call[2] == "dhan"
    assert call[3] == "2026-01"


def test_inserted_count_returned_unchanged() -> None:
    port = FakeMarketDataPort((_candle(),))
    assert (
        ingest_historical_candles(
            market_data=port,
            store=FakeMarketDataStore(inserted=0),
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=T0,
            source_id="dhan",
        )
        == 0
    )


def test_empty_upstream_returns_zero_without_fabrication() -> None:
    port = FakeMarketDataPort(())
    store = FakeMarketDataStore()

    assert (
        ingest_historical_candles(
            market_data=port,
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=T1,
            source_id="dhan",
        )
        == 0
    )

    (call,) = store.calls
    assert call[1] == ()


def test_naive_start_rejected_before_upstream_call() -> None:
    port = FakeMarketDataPort((_candle(),))
    store = FakeMarketDataStore()

    with pytest.raises(ValueError, match="timezone-aware"):
        ingest_historical_candles(
            market_data=port,
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=datetime(2026, 1, 1, 9, 15),
            end=T1,
            source_id="dhan",
        )

    assert port.calls == []
    assert store.calls == []


def test_naive_end_rejected_before_upstream_call() -> None:
    port = FakeMarketDataPort((_candle(),))
    store = FakeMarketDataStore()

    with pytest.raises(ValueError, match="timezone-aware"):
        ingest_historical_candles(
            market_data=port,
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=datetime(2026, 1, 1, 9, 16),
            source_id="dhan",
        )

    assert port.calls == []
    assert store.calls == []


def test_end_before_start_rejected_before_upstream_call() -> None:
    port = FakeMarketDataPort((_candle(),))
    store = FakeMarketDataStore()

    with pytest.raises(ValueError, match="must not precede start"):
        ingest_historical_candles(
            market_data=port,
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=T1,
            end=T0,
            source_id="dhan",
        )

    assert port.calls == []
    assert store.calls == []


def test_upstream_failure_propagates_without_save() -> None:
    class FailingPort(FakeMarketDataPort):
        def candles(self, instrument, *, timeframe, start, end):
            raise RuntimeError("vendor unavailable")

    store = FakeMarketDataStore()

    with pytest.raises(RuntimeError, match="vendor unavailable"):
        ingest_historical_candles(
            market_data=FailingPort(),
            store=store,
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=T1,
            source_id="dhan",
        )

    assert store.calls == []


def test_store_conflict_propagates_without_swallowing() -> None:
    class ConflictingStore(FakeMarketDataStore):
        def save_candles(self, candles, *, source_id, dataset_version=""):
            raise ValueError("conflicting market candle already stored")

    with pytest.raises(ValueError, match="conflicting market candle"):
        ingest_historical_candles(
            market_data=FakeMarketDataPort((_candle(),)),
            store=ConflictingStore(),
            instrument=TCS,
            timeframe="1m",
            start=T0,
            end=T0,
            source_id="dhan",
        )


def test_bridge_uses_vendor_neutral_protocols_only() -> None:
    port = FakeMarketDataPort((_candle(),))
    store = FakeMarketDataStore()

    assert isinstance(port, MarketDataPort)
    assert isinstance(store, MarketDataStore)

    ingest_historical_candles(
        market_data=port,
        store=store,
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T0,
        source_id="dhan",
    )


def test_no_float_conversion_in_persisted_values() -> None:
    candles = (
        _candle(
            open=Decimal("0.1"),
            high=Decimal("0.100000000000000001"),
            low=Decimal("0.1"),
            close=Decimal("0.100000000000000001"),
            volume=Decimal("0.1"),
        ),
    )
    port = FakeMarketDataPort(candles)
    store = FakeMarketDataStore()

    ingest_historical_candles(
        market_data=port,
        store=store,
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T0,
        source_id="dhan",
    )

    (call,) = store.calls
    assert str(call[1][0].open) == "0.1"
    assert str(call[1][0].close) == "0.100000000000000001"


def test_exact_call_sequencing_read_then_save() -> None:
    events: list = []

    class SequencedPort(FakeMarketDataPort):
        def candles(self, instrument, *, timeframe, start, end):
            events.append("candles")
            return super().candles(instrument, timeframe=timeframe, start=start, end=end)

    class SequencedStore(FakeMarketDataStore):
        def save_candles(self, candles, *, source_id, dataset_version=""):
            events.append("save_candles")
            return super().save_candles(
                candles, source_id=source_id, dataset_version=dataset_version
            )

    ingest_historical_candles(
        market_data=SequencedPort((_candle(),)),
        store=SequencedStore(),
        instrument=TCS,
        timeframe="1m",
        start=T0,
        end=T0,
        source_id="dhan",
    )

    assert events == ["candles", "save_candles"]


def test_dhan_style_candles_ingest_into_sqlite_store() -> None:
    candles = (
        _candle(T0, open=Decimal("99.5"), close=Decimal("100.25"), volume=Decimal("1500")),
        _candle(T1, open=Decimal("100.25"), close=Decimal("101"), volume=Decimal("1600")),
    )
    with tempfile.TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "quantx.db")
        try:
            store = SqliteMarketDataStore(database)
            port = FakeMarketDataPort(candles)

            inserted = ingest_historical_candles(
                market_data=port,
                store=store,
                instrument=TCS,
                timeframe="1m",
                start=T0,
                end=T1,
                source_id="dhan",
                dataset_version="2026-01",
            )
            retrieved = store.get_candles(TCS, timeframe="1m", start=T0, end=T1)
        finally:
            database.close()

    assert inserted == 2
    assert retrieved == candles
