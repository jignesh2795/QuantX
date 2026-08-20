from datetime import datetime, timedelta, timezone

from quantx.research.data import HistoricalObservation
from quantx.research.quality import DataQualityStatus, HistoricalDataQualityGate


def _obs(ts, sequence=0, instrument="NSE:TCS"):
    return HistoricalObservation(
        instrument=instrument,
        timestamp=ts,
        sequence=sequence,
        source_id="test-source",
        dataset_version="v1",
        market_snapshot={"last": "100"},
    )


def test_complete_series_is_replayable():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start), _obs(start + timedelta(seconds=60), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.status is DataQualityStatus.COMPLETE
    assert report.can_replay


def test_gap_is_incomplete_not_repaired():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start), _obs(start + timedelta(seconds=180), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.status is DataQualityStatus.INCOMPLETE
    assert not any("fabricated" in issue.message.lower() for issue in report.issues)


def test_instrument_mismatch_blocks_replay():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start, instrument="NSE:INFY"),)
    report = HistoricalDataQualityGate().validate(observations, expected_instrument="NSE:TCS")
    assert report.status is DataQualityStatus.BLOCKED
