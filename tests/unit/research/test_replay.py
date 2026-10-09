from datetime import UTC, datetime, timezone
from decimal import Decimal

import pytest

from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.replay import HistoricalReplay


def _obs(ts: str, sequence: int) -> HistoricalObservation:
    timestamp = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
    )
    return HistoricalObservation(snapshot, "fixture", "v1", sequence)


def test_series_is_chronological_and_point_in_time() -> None:
    series = HistoricalDataSeries(
        [
            _obs("2026-01-01T10:00:01", 1),
            _obs("2026-01-01T10:00:00", 0),
        ]
    )
    cutoff = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    values = series.as_of(cutoff)
    assert len(values) == 1
    assert values[0].snapshot.timestamp == cutoff


def test_replay_never_reorders_or_looks_ahead() -> None:
    series = HistoricalDataSeries(
        [
            _obs("2026-01-01T10:00:02", 2),
            _obs("2026-01-01T10:00:00", 0),
            _obs("2026-01-01T10:00:01", 1),
        ]
    )
    replay = HistoricalReplay(series)
    seen = []
    count = replay.run(lambda frame: seen.append(frame.observation.snapshot.timestamp))
    assert count == 3
    assert seen == sorted(seen)


def test_missing_metadata_is_rejected() -> None:
    with pytest.raises(ValueError, match="source_id"):
        HistoricalObservation(
            _obs("2026-01-01T10:00:00", 0).snapshot,
            "",
            "v1",
            0,
        )


def _obs_tcs(ts: str, sequence: int) -> HistoricalObservation:
    timestamp = datetime.fromisoformat(ts).replace(tzinfo=UTC)
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
    )
    return HistoricalObservation(snapshot, "fixture", "v1", sequence)


def _obs_infy(ts: str, sequence: int) -> HistoricalObservation:
    timestamp = datetime.fromisoformat(ts).replace(tzinfo=UTC)
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "INFY"),
        timestamp=timestamp,
        bid=Decimal("199"),
        ask=Decimal("200"),
    )
    return HistoricalObservation(snapshot, "fixture", "v1", sequence)


def test_single_series_behavior_unchanged() -> None:
    series = HistoricalDataSeries(
        [
            _obs("2026-01-01T10:00:01", 1),
            _obs("2026-01-01T10:00:00", 0),
        ]
    )
    replay = HistoricalReplay(series)
    frames = replay.frames()
    assert len(frames) == 2
    assert frames[0].index == 0
    assert frames[1].index == 1


def test_multi_series_replay_accepts_multiple_series() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:00", 0),
            _obs_tcs("2026-01-01T10:00:01", 1),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:00", 0),
            _obs_infy("2026-01-01T10:00:01", 1),
        ]
    )
    replay = HistoricalReplay((tcs_series, infy_series))
    frames = replay.frames()
    assert len(frames) == 4


def test_interleaved_observations_merged_deterministically() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:01", 1),
            _obs_tcs("2026-01-01T10:00:00", 0),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:00", 0),
            _obs_infy("2026-01-01T10:00:02", 1),
        ]
    )
    replay = HistoricalReplay((tcs_series, infy_series))
    frames = replay.frames()
    assert len(frames) == 4
    timestamps = [f.observation.snapshot.timestamp for f in frames]
    assert timestamps == sorted(timestamps)
    # Check instrument identity preserved
    instruments = [f.observation.instrument for f in frames]
    assert instruments[0] == InstrumentId("NSE", "INFY")  # 10:00:00 INFY
    assert instruments[1] == InstrumentId("NSE", "TCS")  # 10:00:00 TCS
    assert instruments[2] == InstrumentId("NSE", "TCS")  # 10:00:01 TCS
    assert instruments[3] == InstrumentId("NSE", "INFY")  # 10:00:02 INFY


def test_equal_timestamps_different_instruments_not_duplicates() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:00", 0),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:00", 0),
        ]
    )
    replay = HistoricalReplay((tcs_series, infy_series))
    frames = replay.frames()
    assert len(frames) == 2
    # Same timestamp, same sequence, different instruments: both replay in
    # deterministic instrument-identity order, never collapsed as duplicates.
    assert [f.observation.instrument for f in frames] == [
        InstrumentId("NSE", "INFY"),
        InstrumentId("NSE", "TCS"),
    ]


def test_point_in_time_ordering_causal() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:02", 2),
            _obs_tcs("2026-01-01T10:00:00", 0),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:01", 1),
        ]
    )
    replay = HistoricalReplay((infy_series, tcs_series))
    frames = replay.frames()
    assert [frame.index for frame in frames] == [0, 1, 2]
    timestamps = [f.observation.snapshot.timestamp for f in frames]
    assert timestamps == sorted(timestamps)
    # No frame observes a future observation: each frame carries its own
    # observation and the merged stream never looks ahead.
    assert [f.observation.instrument for f in frames] == [
        InstrumentId("NSE", "TCS"),
        InstrumentId("NSE", "INFY"),
        InstrumentId("NSE", "TCS"),
    ]


def test_multi_series_rejects_ambiguous_expected_instrument() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:00", 0),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:00", 0),
        ]
    )
    replay = HistoricalReplay(
        (tcs_series, infy_series),
        expected_instrument=InstrumentId("NSE", "TCS"),
    )
    with pytest.raises(ValueError, match="expected_instrument"):
        replay.frames()


def test_each_frame_preserves_instrument_identity() -> None:
    tcs_series = HistoricalDataSeries(
        [
            _obs_tcs("2026-01-01T10:00:00", 0),
        ]
    )
    infy_series = HistoricalDataSeries(
        [
            _obs_infy("2026-01-01T10:00:00", 0),
        ]
    )
    replay = HistoricalReplay((tcs_series, infy_series))
    frames = replay.frames()
    for frame in frames:
        assert frame.observation.instrument in (
            InstrumentId("NSE", "TCS"),
            InstrumentId("NSE", "INFY"),
        )
