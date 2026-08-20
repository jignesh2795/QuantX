from datetime import datetime, timezone
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
    series = HistoricalDataSeries([
        _obs("2026-01-01T10:00:01", 1),
        _obs("2026-01-01T10:00:00", 0),
    ])
    cutoff = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    values = series.as_of(cutoff)
    assert len(values) == 1
    assert values[0].snapshot.timestamp == cutoff


def test_replay_never_reorders_or_looks_ahead() -> None:
    series = HistoricalDataSeries([
        _obs("2026-01-01T10:00:02", 2),
        _obs("2026-01-01T10:00:00", 0),
        _obs("2026-01-01T10:00:01", 1),
    ])
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
