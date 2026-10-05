from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.research.calendar import FixedDailySessionCalendar
from quantx.research.data import HistoricalObservation
from quantx.research.quality import (
    CompletenessStatus,
    DataIssueType,
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


class _UnknownCalendar:
    version = "unknown-calendar-v1"

    def historical_timestamp_expected(self, timestamp):
        return None


def test_calendar_aware_gap_ignores_closed_period() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    friday = datetime(2026, 1, 2, 15, 29, tzinfo=UTC)
    monday = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)

    result = HistoricalDataQualityGate().validate(
        (_obs(friday), _obs(monday, 1)),
        expected_interval_seconds=60,
        calendar=calendar,
    )

    assert result.quality is DataQualityStatus.VALID_WITH_WARNINGS
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.calendar_version == "fixed-daily-v1"
    assert result.calendar_unknown_timestamps == ()
    assert all(
        issue.issue_type is not DataIssueType.GAP for issue in result.issues
    )


def test_calendar_aware_gap_detects_missing_open_slot() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    start = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
    end = datetime(2026, 1, 5, 9, 17, tzinfo=UTC)

    result = HistoricalDataQualityGate().validate(
        (_obs(start), _obs(end, 1)),
        expected_interval_seconds=60,
        calendar=calendar,
    )

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert any(issue.issue_type is DataIssueType.GAP for issue in result.issues)


def test_unknown_calendar_is_explicit_and_does_not_infer_gap() -> None:
    start = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
    end = datetime(2026, 1, 5, 9, 17, tzinfo=UTC)

    result = HistoricalDataQualityGate().validate(
        (_obs(start), _obs(end, 1)),
        expected_interval_seconds=60,
        calendar=_UnknownCalendar(),
    )

    assert result.quality is DataQualityStatus.DEGRADED
    assert result.completeness is CompletenessStatus.UNKNOWN
    assert result.calendar_version == "unknown-calendar-v1"
    assert result.calendar_unknown_timestamps == (
        datetime(2026, 1, 5, 9, 16, tzinfo=UTC),
    )
    assert all(issue.issue_type is not DataIssueType.GAP for issue in result.issues)
    assert any(
        issue.issue_type is DataIssueType.CALENDAR_UNKNOWN
        for issue in result.issues
    )


def test_invalid_expected_interval_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        HistoricalDataQualityGate().validate(
            (_obs(datetime(2026, 1, 5, 9, 15, tzinfo=UTC)),),
            expected_interval_seconds=0,
        )


def test_complete_interval_series_is_replayable_but_completeness_is_unknown():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = (_obs(start), _obs(start + timedelta(seconds=60), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.quality is DataQualityStatus.VALID_WITH_WARNINGS
    assert report.status is DataQualityStatus.COMPLETE
    assert report.completeness is CompletenessStatus.UNKNOWN
    assert report.can_replay


def test_explicit_expected_timestamps_establish_completeness():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = (_obs(start), _obs(start + timedelta(seconds=60), 1))
    report = HistoricalDataQualityGate().validate(
        observations,
        expected_timestamps=(start, start + timedelta(seconds=60)),
    )
    assert report.quality is DataQualityStatus.VALID
    assert report.completeness is CompletenessStatus.COMPLETE


def test_gap_is_incomplete_not_repaired():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = (_obs(start), _obs(start + timedelta(seconds=180), 1))
    report = HistoricalDataQualityGate().validate(observations, expected_interval_seconds=60)
    assert report.status is DataQualityStatus.INCOMPLETE
    assert report.completeness is CompletenessStatus.UNKNOWN
    assert not any("fabricated" in issue.message.lower() for issue in report.issues)


def test_instrument_mismatch_blocks_replay():
    start = datetime(2026, 1, 1, tzinfo=UTC)
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
    clean = HistoricalDataQualityGate().validate((_obs(datetime(2026, 1, 1, tzinfo=UTC)),))
    assert clean.quality is DataQualityStatus.VALID_WITH_WARNINGS
    assert clean.status is DataQualityStatus.COMPLETE
