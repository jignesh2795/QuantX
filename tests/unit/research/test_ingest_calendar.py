from datetime import datetime, time
from zoneinfo import ZoneInfo

from quantx.research.calendar import FixedDailySessionCalendar, SessionStatus
from quantx.research.ingest import CanonicalOHLCVNormalizer, RawMarketRecord


def test_calendar_classifies_open_and_closed_times() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="Asia/Kolkata",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )

    open_result = calendar.classify(datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("UTC")))
    closed_result = calendar.classify(datetime(2026, 8, 20, 11, 0, tzinfo=ZoneInfo("UTC")))

    assert open_result.status is SessionStatus.OPEN
    assert closed_result.status is SessionStatus.CLOSED


def test_normalizer_preserves_session_classification() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="Asia/Kolkata",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    normalizer = CanonicalOHLCVNormalizer(
        dataset_id="source-1",
        dataset_version="2026-08-20",
        calendar=calendar,
    )
    record = RawMarketRecord(
        timestamp=datetime(2026, 8, 20, 5, 0, tzinfo=ZoneInfo("UTC")),
        instrument="NIFTY",
        sequence=1,
        fields={"open": 1, "high": 2, "low": 0.5, "close": 1.5},
    )

    observation = normalizer.normalize(record)

    assert observation.data["session_status"] == SessionStatus.OPEN.value
    assert observation.data["calendar_version"] == "fixed-daily-v1"


def test_normalizer_rejects_naive_timestamp() -> None:
    normalizer = CanonicalOHLCVNormalizer(dataset_id="source-1", dataset_version="v1")
    record = RawMarketRecord(
        timestamp=datetime(2026, 8, 20, 10, 0),
        instrument="NIFTY",
        sequence=1,
        fields={"open": 1, "high": 2, "low": 0.5, "close": 1.5},
    )

    try:
        normalizer.normalize(record)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("expected naive timestamp to be rejected")
