"""Tests for the SQLite vendor-neutral market-data store."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.instruments import InstrumentId
from quantx.domain.market_data import Candle, Quote
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.idempotency import SqliteIdempotencyStore
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.ports.market_data import MarketDataStore

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

TCS = InstrumentId("NSE", "TCS")
INFY = InstrumentId("NSE", "INFY")


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


def _quote(timestamp: datetime = T0, **overrides) -> Quote:
    values = {
        "instrument": TCS,
        "timestamp": timestamp,
        "bid": Decimal("99"),
        "ask": Decimal("100"),
        "last": Decimal("100"),
        "bid_size": Decimal("10"),
        "ask_size": Decimal("12"),
    }
    values.update(overrides)
    return Quote(**values)


def _store(tmp_path) -> tuple[SqliteDatabase, SqliteMarketDataStore]:
    database = SqliteDatabase(tmp_path / "quantx.db")
    return database, SqliteMarketDataStore(database)


def test_store_conforms_to_market_data_store_port(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert isinstance(store, MarketDataStore)
    finally:
        database.close()


def test_candle_insert_and_retrieve_round_trip(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert store.save_candles((_candle(),), source_id="dhan") == 1

        (retrieved,) = store.get_candles(TCS, timeframe="1m", start=T0, end=T0)

        assert retrieved == _candle()
    finally:
        database.close()


def test_quote_insert_and_retrieve_round_trip(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert store.save_quotes((_quote(),), source_id="dhan") == 1

        (retrieved,) = store.get_quotes(TCS, start=T0, end=T0)

        assert retrieved == _quote()
    finally:
        database.close()


def test_decimal_values_round_trip_exactly(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        values = [
            Decimal("0.1"),
            Decimal("0.100000000000000001"),
            Decimal("123456789.123456789"),
        ]
        for index, value in enumerate(values):
            candle = _candle(
                timestamp=datetime(2026, 1, 1, 9, 15 + index, tzinfo=UTC),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=value,
            )
            assert store.save_candles((candle,), source_id="dhan") == 1

        retrieved = store.get_candles(
            TCS,
            timeframe="1m",
            start=T0,
            end=datetime(2026, 1, 1, 9, 18, tzinfo=UTC),
        )

        assert [candle.open for candle in retrieved] == values
        assert [str(candle.open) for candle in retrieved] == [str(value) for value in values]
    finally:
        database.close()


def test_naive_timestamps_rejected(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        naive = datetime(2026, 1, 1, 9, 15)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.get_candles(TCS, timeframe="1m", start=naive, end=T1)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.get_quotes(TCS, start=T0, end=naive)
        with pytest.raises(ValueError, match="timezone-aware"):
            Quote(TCS, naive, bid=Decimal("1"))
    finally:
        database.close()


def test_candle_range_end_precedes_start_rejected(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        with pytest.raises(ValueError, match="must not precede start"):
            store.get_candles(TCS, timeframe="1m", start=T1, end=T0)
    finally:
        database.close()


def test_candles_isolated_by_instrument(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(),), source_id="dhan")
        store.save_candles((_candle(instrument=INFY),), source_id="dhan")

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T2)) == 1
        assert len(store.get_candles(INFY, timeframe="1m", start=T0, end=T2)) == 1
    finally:
        database.close()


def test_candles_isolated_by_timeframe(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(timeframe="1m"),), source_id="dhan")
        store.save_candles((_candle(timeframe="1d"),), source_id="dhan")

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T2)) == 1
        assert len(store.get_candles(TCS, timeframe="1d", start=T0, end=T2)) == 1
    finally:
        database.close()


def test_candles_returned_in_chronological_order(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(T2), _candle(T0), _candle(T1)), source_id="dhan")

        retrieved = store.get_candles(TCS, timeframe="1m", start=T0, end=T2)

        assert [candle.timestamp for candle in retrieved] == [T0, T1, T2]
    finally:
        database.close()


def test_candle_range_boundaries_are_inclusive(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(T0), _candle(T1), _candle(T2)), source_id="dhan")

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0)) == 1
        assert len(store.get_candles(TCS, timeframe="1m", start=T1, end=T1)) == 1
        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T1)) == 2
    finally:
        database.close()


def test_identical_duplicate_candle_is_idempotent(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert store.save_candles((_candle(),), source_id="dhan") == 1
        assert store.save_candles((_candle(),), source_id="dhan") == 0

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0)) == 1
    finally:
        database.close()


def test_conflicting_duplicate_candle_rejected(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(),), source_id="dhan")

        with pytest.raises(ValueError, match="conflicting market candle"):
            store.save_candles((_candle(close=Decimal("101")),), source_id="dhan")

        (retrieved,) = store.get_candles(TCS, timeframe="1m", start=T0, end=T0)
        assert retrieved.close == Decimal("100")
    finally:
        database.close()


def test_identical_duplicate_quote_is_idempotent(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert store.save_quotes((_quote(),), source_id="dhan") == 1
        assert store.save_quotes((_quote(),), source_id="dhan") == 0
    finally:
        database.close()


def test_conflicting_duplicate_quote_rejected(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_quotes((_quote(),), source_id="dhan")

        with pytest.raises(ValueError, match="conflicting market quote"):
            store.save_quotes((_quote(last=Decimal("101")),), source_id="dhan")
    finally:
        database.close()


def test_multiple_instruments_coexist(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(), _candle(instrument=INFY)), source_id="dhan")
        store.save_quotes((_quote(), _quote(instrument=INFY)), source_id="dhan")

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T2)) == 1
        assert len(store.get_quotes(INFY, start=T0, end=T2)) == 1
    finally:
        database.close()


def test_multiple_timeframes_coexist(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles(
            (_candle(timeframe="1m"), _candle(timeframe="5m"), _candle(timeframe="1d")),
            source_id="dhan",
        )

        assert len(store.get_candles(TCS, timeframe="5m", start=T0, end=T2)) == 1
    finally:
        database.close()


def test_quote_optional_fields_preserved_as_none(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        quote = _quote(bid=None, ask=None, last=Decimal("100"), bid_size=None, ask_size=None)
        store.save_quotes((quote,), source_id="dhan")

        (retrieved,) = store.get_quotes(TCS, start=T0, end=T0)

        assert retrieved.bid is None
        assert retrieved.ask is None
        assert retrieved.last == Decimal("100")
        assert retrieved.bid_size is None
        assert retrieved.ask_size is None
    finally:
        database.close()


def test_candle_volume_preserved(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles(
            (_candle(volume=Decimal("0")), _candle(T1, volume=Decimal("123456789"))),
            source_id="dhan",
        )

        retrieved = store.get_candles(TCS, timeframe="1m", start=T0, end=T2)

        assert [candle.volume for candle in retrieved] == [Decimal("0"), Decimal("123456789")]
    finally:
        database.close()


def test_store_survives_database_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    first = SqliteDatabase(path)
    try:
        SqliteMarketDataStore(first).save_candles((_candle(),), source_id="dhan")
        SqliteMarketDataStore(first).save_quotes((_quote(),), source_id="dhan")
    finally:
        first.close()

    second = SqliteDatabase(path)
    try:
        store = SqliteMarketDataStore(second)
        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0)) == 1
        assert len(store.get_quotes(TCS, start=T0, end=T0)) == 1
    finally:
        second.close()


def test_source_identity_distinguishes_rows(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(),), source_id="dhan")
        store.save_candles((_candle(),), source_id="dhan", dataset_version="v2")
        store.save_candles((_candle(),), source_id="other-venue")

        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0)) == 3
        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0, source_id="dhan")) == 2
        assert (
            len(
                store.get_candles(
                    TCS,
                    timeframe="1m",
                    start=T0,
                    end=T0,
                    source_id="dhan",
                    dataset_version="v2",
                )
            )
            == 1
        )
    finally:
        database.close()


def test_existing_tables_remain_usable(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(),), source_id="dhan")
        decision = SqliteIdempotencyStore(database).reserve_or_get(uuid4(), "fp")
        assert decision.reservation_acquired
        assert len(store.get_candles(TCS, timeframe="1m", start=T0, end=T0)) == 1
    finally:
        database.close()


def test_empty_query_returns_empty_tuple(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        assert store.get_candles(TCS, timeframe="1m", start=T0, end=T2) == ()
        assert store.get_quotes(INFY, start=T0, end=T2) == ()
    finally:
        database.close()


def test_unknown_instrument_returns_nothing(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        store.save_candles((_candle(),), source_id="dhan")

        assert store.get_candles(INFY, timeframe="1m", start=T0, end=T2) == ()
        assert store.get_candles(TCS, timeframe="1d", start=T0, end=T2) == ()
    finally:
        database.close()


def test_stored_decimals_use_exact_text_representation(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        value = Decimal("0.100000000000000001")
        store.save_candles(
            (
                _candle(
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=value,
                ),
            ),
            source_id="dhan",
        )
        row = database.connection().execute("SELECT open FROM market_candles").fetchone()

        assert row[0] == "0.100000000000000001"
    finally:
        database.close()


def test_source_id_required(tmp_path) -> None:
    database, store = _store(tmp_path)
    try:
        with pytest.raises(ValueError, match="source_id"):
            store.save_candles((_candle(),), source_id="  ")
        with pytest.raises(ValueError, match="source_id"):
            store.save_quotes((_quote(),), source_id="")
    finally:
        database.close()
