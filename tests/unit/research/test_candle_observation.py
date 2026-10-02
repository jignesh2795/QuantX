"""Lossless canonical-Candle research observation coverage.

A canonical ``Candle`` must enter ``HistoricalObservation`` without any
information loss: no Quote projection, no OHLCV re-encoding, no synthetic
bid/ask fields, and no parallel Candle-like research structure.
Quote-backed observations keep working unchanged.
"""

import dataclasses
import inspect
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_access import (
    candles_to_observations,
    read_candles,
    read_observations,
)
from quantx.research.dataset_catalog import InMemoryDatasetCatalog
from quantx.research.replay import HistoricalReplay, ReplayFrame

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

TCS = InstrumentId("NSE", "TCS")

# Unusually precise fixtures so accidental float conversion is detectable.
PRECISE = {
    "open": Decimal("100.100000000000000001"),
    "high": Decimal("101.00000000000001"),
    "low": Decimal("99.09799999999999999"),
    "close": Decimal("100.00000000000001"),
    "volume": Decimal("123456789.123456789"),
}


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


def _quote(timestamp: datetime = T0, sequence: int = 0) -> HistoricalObservation:
    snapshot = MarketSnapshot(
        instrument=TCS,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalObservation(snapshot, "fixture", "v1", sequence)


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


# 1. Quote-backed HistoricalObservation remains compatible.
def test_quote_backed_observation_remains_compatible() -> None:
    obs = _quote(T0, 0)

    assert obs.snapshot.last == Decimal("100")
    assert obs.snapshot.bid == Decimal("99")
    assert obs.snapshot.ask == Decimal("100")
    assert obs.snapshot.instrument == TCS
    assert obs.snapshot.timestamp == T0
    assert obs.instrument == TCS
    assert obs.timestamp == T0
    assert obs.source_id == "fixture"
    assert obs.dataset_version == "v1"
    assert obs.sequence == 0


# 2. Candle-backed HistoricalObservation can be constructed.
def test_candle_backed_observation_constructs() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 0)

    assert isinstance(obs, HistoricalObservation)
    assert obs.timestamp == T0
    assert obs.instrument == TCS


# 3. Candle payload is preserved exactly.
def test_candle_payload_preserved_exactly() -> None:
    candle = _candle(T0)
    obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)

    assert obs.snapshot is candle
    assert obs.snapshot == candle


# 4. OHLCV values are preserved exactly.
def test_ohlcv_values_preserved_exactly() -> None:
    candle = _candle(T0, **PRECISE)
    obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)

    assert obs.snapshot.open == PRECISE["open"]
    assert obs.snapshot.high == PRECISE["high"]
    assert obs.snapshot.low == PRECISE["low"]
    assert obs.snapshot.close == PRECISE["close"]
    assert obs.snapshot.volume == PRECISE["volume"]


# 5. Timeframe is preserved.
def test_timeframe_preserved() -> None:
    for timeframe in ("1m", "5m", "15m", "1h", "1d"):
        candle = _candle(T0, timeframe=timeframe)
        obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)

        assert obs.snapshot.timeframe == timeframe


# 6. Instrument is preserved.
def test_instrument_preserved() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 0)

    assert obs.instrument == TCS
    assert obs.snapshot.instrument == TCS


# 7. Timestamp is preserved.
def test_timestamp_preserved() -> None:
    obs = HistoricalObservation.from_candle(_candle(T1), "fixture", "v1", 0)

    assert obs.timestamp == T1
    assert obs.snapshot.timestamp == T1


# 8. source_id preserved.
def test_source_id_preserved() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "csv-import", "v1", 0)

    assert obs.source_id == "csv-import"


# 9. dataset_version preserved.
def test_dataset_version_preserved() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "2026-01", 0)

    assert obs.dataset_version == "2026-01"


# 10. sequence preserved.
def test_sequence_preserved() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 7)

    assert obs.sequence == 7


# 11. HistoricalDataSeries accepts candle observations.
def test_series_accepts_candle_observations() -> None:
    observations = tuple(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )
    series = HistoricalDataSeries(observations)

    assert len(series) == 3
    assert series.instrument == TCS
    assert series.as_tuple() == tuple(sorted(observations, key=lambda item: item.timestamp))


# 12. Mixed Quote/Candle observations with the same instrument are supported.
def test_mixed_quote_and_candle_same_instrument_supported() -> None:
    quote_obs = _quote(T0, 0)
    candle_obs = HistoricalObservation.from_candle(_candle(T1), "fixture", "v1", 1)
    series = HistoricalDataSeries((quote_obs, candle_obs))

    assert len(series) == 2
    assert series.instrument == TCS
    assert series.as_tuple()[0].timestamp == T0
    assert series.as_tuple()[1].timestamp == T1


# 13. Series ordering remains deterministic.
def test_series_ordering_remains_deterministic() -> None:
    first = HistoricalObservation.from_candle(_candle(T2), "fixture", "v1", 2)
    second = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 0)
    third = HistoricalObservation.from_candle(_candle(T1), "fixture", "v1", 1)

    assert [obs.timestamp for obs in HistoricalDataSeries((first, second, third))] == [T0, T1, T2]
    assert [obs.timestamp for obs in HistoricalDataSeries((third, first, second))] == [T0, T1, T2]


# 14. as_of works with candle-backed observations.
def test_as_of_with_candle_observations() -> None:
    series = HistoricalDataSeries(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )

    assert tuple(item.timestamp for item in series.as_of(T1)) == (T0, T1)
    assert series.as_of(datetime(2026, 1, 1, 9, 14, tzinfo=UTC)) == ()


# 15. between works with candle-backed observations.
def test_between_with_candle_observations() -> None:
    series = HistoricalDataSeries(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )

    assert tuple(item.timestamp for item in series.between(T0, T2)) == (T0, T1, T2)
    assert tuple(item.timestamp for item in series.between(T1, T2)) == (T1, T2)


# 16. latest_at_or_before works with candle-backed observations.
def test_latest_at_or_before_with_candle_observations() -> None:
    series = HistoricalDataSeries(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )

    assert series.latest_at_or_before(T1) is not None
    assert series.latest_at_or_before(T1).timestamp == T1  # type: ignore[union-attr]
    assert series.latest_at_or_before(T2).snapshot.close == Decimal("100")  # type: ignore[union-attr]
    assert series.latest_at_or_before(datetime(2026, 1, 1, 9, 14, tzinfo=UTC)) is None


class _RecordingResolver:
    """Point-in-time resolver double recording exact resolution inputs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime]] = []

    def resolve(self, instrument_id: str, timestamp: datetime):
        self.calls.append((instrument_id, timestamp))
        return None


# 17. HistoricalReplay works with candle-backed observations.
def test_replay_with_candle_observations() -> None:
    series = HistoricalDataSeries(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )

    assert HistoricalReplay(series).run(lambda _frame: None) == 3


# 18. Point-in-time resolution still receives exact instrument/timestamp.
def test_replay_point_in_time_receives_exact_instrument_timestamp() -> None:
    series = HistoricalDataSeries(
        HistoricalObservation.from_candle(_candle(ts), "fixture", "v1", index)
        for index, ts in enumerate((T0, T1, T2))
    )
    resolver = _RecordingResolver()
    frames = HistoricalReplay(series, point_in_time_resolver=resolver).frames()  # type: ignore[arg-type]

    assert [frame.observation.timestamp for frame in frames] == [T0, T1, T2]
    assert resolver.calls == [(str(TCS), T0), (str(TCS), T1), (str(TCS), T2)]
    assert all(isinstance(frame, ReplayFrame) for frame in frames)


# 19. Existing quote-based replay behavior remains green.
def test_quote_based_replay_behavior_unchanged() -> None:
    series = HistoricalDataSeries((_quote(T1, 1), _quote(T0, 0)))
    seen: list[datetime] = []
    count = HistoricalReplay(series).run(lambda frame: seen.append(frame.observation.timestamp))

    assert count == 2
    assert seen == [T0, T1]
    assert seen == sorted(seen)


# 20. Candle is never converted to Quote.
def test_candle_never_converted_to_quote() -> None:
    candle = _candle(T0, **PRECISE)
    obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)

    assert isinstance(obs.snapshot, Candle)
    assert not isinstance(obs.snapshot, Quote)
    assert type(obs.snapshot) is Candle


# 21. No synthetic bid/ask fields are created.
def test_no_synthetic_bid_ask_fields_created() -> None:
    obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 0)

    assert not hasattr(obs.snapshot, "bid")
    assert not hasattr(obs.snapshot, "ask")
    assert not hasattr(obs.snapshot, "bid_size")
    assert not hasattr(obs.snapshot, "ask_size")
    assert not hasattr(obs.snapshot, "last")
    assert not hasattr(obs.snapshot, "mid")
    assert not hasattr(obs.snapshot, "spread")


# 22. Underlying Candle validation remains authoritative.
def test_underlying_candle_validation_authoritative() -> None:
    with pytest.raises(ValueError, match="candle prices cannot be negative"):
        _candle(T0, open=Decimal("-1"))
    with pytest.raises(ValueError, match="candle volume cannot be negative"):
        _candle(T0, volume=Decimal("-1"))
    with pytest.raises(ValueError, match="candle high/low do not contain open/close"):
        _candle(T0, high=Decimal("90"), low=Decimal("100"))
    with pytest.raises(ValueError, match="timeframe must not be empty"):
        _candle(T0, timeframe="  ")
    with pytest.raises(ValueError, match="candle timestamp must be timezone-aware"):
        _candle(datetime(2026, 1, 1, 9, 15))
    with pytest.raises(TypeError, match="canonical Candle"):
        HistoricalObservation.from_candle("not-a-candle", "fixture", "v1", 0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        HistoricalObservation("not-a-snapshot", "fixture", "v1", 0)  # type: ignore[arg-type]


# 23. source/dataset/sequence validation remains intact.
def test_source_dataset_sequence_validation_intact() -> None:
    with pytest.raises(ValueError, match="source_id must not be empty"):
        HistoricalObservation.from_candle(_candle(T0), "  ", "v1", 0)
    with pytest.raises(ValueError, match="dataset_version must not be empty"):
        HistoricalObservation.from_candle(_candle(T0), "fixture", "  ", 0)
    with pytest.raises(ValueError, match="sequence must not be negative"):
        HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", -1)
    with pytest.raises(ValueError, match="source_id"):
        HistoricalObservation(_quote(T0).snapshot, "", "v1", 0)


# 24. Precise Decimal values never become float.
def test_precise_decimals_never_become_float() -> None:
    candle = _candle(T0, **PRECISE)
    obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)

    for name in ("open", "high", "low", "close", "volume"):
        value = getattr(obs.snapshot, name)
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)
    assert str(obs.snapshot.open) == "100.100000000000000001"
    assert str(obs.snapshot.high) == "101.00000000000001"
    assert str(obs.snapshot.low) == "99.09799999999999999"
    assert str(obs.snapshot.close) == "100.00000000000001"
    assert str(obs.snapshot.volume) == "123456789.123456789"


# 25. No mutation of the original Candle.
def test_original_candle_not_mutated() -> None:
    candle = _candle(T0, **PRECISE)
    before = (candle.open, candle.high, candle.low, candle.close, candle.volume)
    obs = HistoricalObservation.from_candle(candle, "fixture", "v1", 0)
    series = HistoricalDataSeries(
        (obs, HistoricalObservation.from_candle(_candle(T1), "fixture", "v1", 1))
    )
    HistoricalReplay(series).run(lambda _frame: None)

    assert obs.snapshot is candle
    assert (candle.open, candle.high, candle.low, candle.close, candle.volume) == before


# 26. Frozen observation immutability remains intact.
def test_frozen_observation_immutability_intact() -> None:
    quote_obs = _quote(T0, 0)
    candle_obs = HistoricalObservation.from_candle(_candle(T0), "fixture", "v1", 0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        quote_obs.snapshot = _candle(T0)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        candle_obs.snapshot = _quote(T0).snapshot  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        candle_obs.sequence = 99  # type: ignore[misc]


# 27. Dataset-access candles convert into lossless historical observations.
def test_dataset_access_candles_convert_losslessly() -> None:
    candles = (_candle(T0, **PRECISE), _candle(T1))
    observations = candles_to_observations(candles, source_id="dhan", dataset_version="v1")

    assert len(observations) == 2
    assert [obs.sequence for obs in observations] == [0, 1]
    assert [obs.source_id for obs in observations] == ["dhan", "dhan"]
    assert [obs.dataset_version for obs in observations] == ["v1", "v1"]
    assert observations[0].snapshot is candles[0]
    assert observations[1].snapshot is candles[1]
    assert observations[0].snapshot.open == PRECISE["open"]
    assert observations[0].snapshot.volume == PRECISE["volume"]
    assert all(isinstance(obs.snapshot, Candle) for obs in observations)
    assert all(not isinstance(obs.snapshot, Quote) for obs in observations)


def test_dataset_access_conversion_sequences_and_rejects_bad_metadata() -> None:
    candles = (_candle(T0), _candle(T1))
    observations = candles_to_observations(
        candles, source_id="dhan", dataset_version="v1", start_sequence=5
    )

    assert [obs.sequence for obs in observations] == [5, 6]
    with pytest.raises(ValueError, match="source_id must not be empty"):
        candles_to_observations(candles, source_id="  ", dataset_version="v1")
    with pytest.raises(ValueError, match="dataset_version must not be empty"):
        candles_to_observations(candles, source_id="dhan", dataset_version="  ")
    with pytest.raises(ValueError, match="sequence must not be negative"):
        candles_to_observations(candles, source_id="dhan", dataset_version="v1", start_sequence=-1)


# 28. Vendor neutrality: research preserves caller identity without vendor coupling.
def test_vendor_neutrality() -> None:
    candle = _candle(T0, **PRECISE)
    obs = HistoricalObservation.from_candle(candle, "csv-import", "v1", 0)
    series = HistoricalDataSeries(
        (obs, HistoricalObservation.from_candle(_candle(T1), "csv-import", "v1", 1))
    )

    assert series.instrument == TCS
    assert "csv-import" in {item.source_id for item in series}
    assert str(obs.snapshot.instrument) == str(TCS)
    parameters = inspect.signature(read_candles).parameters
    assert "source_id" not in parameters
    assert "dataset_version" not in parameters


# 29. No network/SDK imports in the lossless research path.
def test_no_network_or_sdk_imports() -> None:
    import quantx.research.data as data_module
    import quantx.research.dataset_access as access_module
    import quantx.research.replay as replay_module

    sources = {
        "data": inspect.getsource(data_module),
        "dataset_access": inspect.getsource(access_module),
        "replay": inspect.getsource(replay_module),
    }
    banned = ("requests", "httpx", "urllib", "socket", "dhan", "sdk", "broker")
    for name, source in sources.items():
        lowered = source.lower()
        assert not any(token in lowered for token in banned), name


# 30. No execution/recovery/LIVE imports in the lossless research path.
def test_no_execution_recovery_live_imports() -> None:
    import quantx.research.data as data_module
    import quantx.research.dataset_access as access_module
    import quantx.research.replay as replay_module

    for module in (data_module, access_module, replay_module):
        for line in inspect.getsource(module).splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "quantx.execution" not in stripped, stripped
                assert "quantx.recovery" not in stripped, stripped
                assert "quantx.brokers" not in stripped, stripped
                assert "LIVE" not in stripped, stripped


def test_integration_dataset_catalog_to_replay_preserves_candles() -> None:
    """DatasetCatalog -> read_candles -> Candle -> observation -> series -> replay."""
    catalog = InMemoryDatasetCatalog()
    catalog.register(_version())
    precise = _candle(T0, **PRECISE)
    second = _candle(T1)

    with tempfile.TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "quantx.db")
        try:
            store = SqliteMarketDataStore(database)
            store.save_candles((precise, second), source_id="dhan", dataset_version="v1")

            candles = read_candles(
                catalog=catalog,
                store=store,
                dataset_id="nse-eq",
                version="v1",
                instrument=TCS,
                timeframe="1m",
                start=T0,
                end=T1,
            )
            assert candles == (precise, second)

            registered = catalog.get("nse-eq", "v1")
            assert registered is not None
            observations = candles_to_observations(
                candles,
                source_id=registered.identity.source_id,
                dataset_version=registered.identity.version,
            )
            series = HistoricalDataSeries(observations)
            replay = HistoricalReplay(series)
            seen: list[Candle] = []
            count = replay.run(lambda frame: seen.append(frame.observation.snapshot))  # type: ignore[arg-type]
        finally:
            database.close()

    assert count == 2
    assert seen == [precise, second]
    assert seen[0].open == PRECISE["open"]
    assert seen[0].high == PRECISE["high"]
    assert seen[0].low == PRECISE["low"]
    assert seen[0].close == PRECISE["close"]
    assert seen[0].volume == PRECISE["volume"]
    assert seen[0].timeframe == "1m"
    assert str(seen[0].open) == "100.100000000000000001"
    assert all(isinstance(item, Candle) for item in seen)
    assert all(not isinstance(item, Quote) for item in seen)


def test_integration_read_observations_convenience_path() -> None:
    catalog = InMemoryDatasetCatalog()
    catalog.register(_version())
    candles = (_candle(T0, **PRECISE), _candle(T1))

    with tempfile.TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "quantx.db")
        try:
            store = SqliteMarketDataStore(database)
            store.save_candles(candles, source_id="dhan", dataset_version="v1")
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
            series = HistoricalDataSeries(observations)
            count = HistoricalReplay(series).run(lambda _frame: None)
        finally:
            database.close()

    assert count == 2
    assert observations[0].snapshot == candles[0]
    assert observations[0].snapshot.open == PRECISE["open"]
    assert [obs.sequence for obs in observations] == [0, 1]
