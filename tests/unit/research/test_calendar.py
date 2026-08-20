from datetime import time, timezone, datetime, timedelta

import pytest

from quantx.research.calendar import FixedDailySessionCalendar, SessionStatus


def test_fixed_daily_calendar_returns_session_for_weekday() -> None:
    calendar = FixedDailySessionCalendar(
        timezone=timezone.utc,
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    timestamp = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    session = calendar.session_for(timestamp)
    assert session is not None
    assert session.status is SessionStatus.OPEN
    assert session.open_at.hour == 9
    assert session.close_at.hour == 15


def test_weekend_is_closed() -> None:
    calendar = FixedDailySessionCalendar(
        timezone=timezone.utc,
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    saturday = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
    assert calendar.session_for(saturday) is None


def test_requires_timezone_aware_timestamp() -> None:
    calendar = FixedDailySessionCalendar(
        timezone=timezone.utc,
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        calendar.session_for(datetime(2026, 8, 20, 10, 0))
