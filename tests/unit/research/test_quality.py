from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.research.data import HistoricalObservation
from quantx.research.quality import (
    CompletenessStatus,
    DataQualityStatus,
    HistoricalDataQualityGate,
)


def _obs(ts, sequence=0, instrument=None):
    inst = instrument or InstrumentId("NSE", "TCS")
    snapshot = MarketSnapshot(
        instrument=inst,
        timestamp=ts,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalObservation(
        snapshot=snapshot,
        source_id="test-source",
        dataset_version="v1",
        sequence=sequence,
    )


def test_complete_interval_series_is_replayable_but_completeness_is_unknown():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start), _obs(start + timedelta(seconds=60), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.status is DataQualityStatus.VALID_WITH_WARNINGS
    assert report.completeness is CompletenessStatus.UNKNOWN
    assert report.can_replay


def test_explicit_expected_timestamps_establish_completeness():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start), _obs(start + timedelta(seconds=60), 1))
    report = HistoricalDataQualityGate().validate(
        observations,
        expected_timestamps=(start, start + timedelta(seconds=60)),
    )
    assert report.quality is DataQualityStatus.VALID
    assert report.completeness is CompletenessStatus.COMPLETE


def test_gap_is_incomplete_not_repaired():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start), _obs(start + timedelta(seconds=180), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.status is DataQualityStatus.INCOMPLETE
    assert report.completeness is CompletenessStatus.INCOMPLETE
    assert not any("fabricated" in issue.message.lower() for issue in report.issues)


def test_instrument_mismatch_blocks_replay():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    observations = (_obs(start, instrument=InstrumentId("NSE", "INFY")),)
    report = HistoricalDataQualityGate().validate(
        observations, expected_instrument=InstrumentId("NSE", "TCS")
    )
    assert report.status is DataQualityStatus.BLOCKED
    assert report.quality is DataQualityStatus.REJECTED


def test_legacy_status_aliases_resolve_to_canonical_members():
    assert DataQualityStatus.COMPLETE is DataQualityStatus.VALID
    assert DataQualityStatus.INCOMPLETE is DataQualityStatus.DEGRADED
    assert DataQualityStatus.BLOCKED is DataQualityStatus.REJECTED
