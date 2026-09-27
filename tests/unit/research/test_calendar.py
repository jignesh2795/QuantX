from datetime import datetime, time, timezone

import pytest

from quantx.research.calendar import FixedDailySessionCalendar, SessionStatus


def test_fixed_daily_calendar_returns_open_session_for_weekday() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    timestamp = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    session = calendar.classify(timestamp)
    assert session.status is SessionStatus.OPEN
    assert session.timezone == "UTC"
    assert session.calendar_version == "fixed-daily-v1"


def test_weekend_is_closed() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    saturday = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
    assert calendar.classify(saturday).status is SessionStatus.CLOSED


def test_requires_timezone_aware_timestamp() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        calendar.classify(datetime(2026, 8, 20, 10, 0))
