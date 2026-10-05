from datetime import UTC, datetime, time

import pytest

from quantx.research.calendar import FixedDailySessionCalendar, SessionStatus


def test_fixed_daily_calendar_returns_open_session_for_weekday() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    timestamp = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
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
    saturday = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
    assert calendar.classify(saturday).status is SessionStatus.CLOSED


def test_requires_timezone_aware_timestamp() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        calendar.classify(datetime(2026, 8, 20, 10, 0))


def test_rejects_invalid_session_bounds() -> None:
    with pytest.raises(ValueError, match="open_time must be before close_time"):
        FixedDailySessionCalendar(
            timezone="UTC",
            open_time=time(15, 30),
            close_time=time(9, 15),
        )
    with pytest.raises(ValueError, match="open_time must be before close_time"):
        FixedDailySessionCalendar(
            timezone="UTC",
            open_time=time(9, 15),
            close_time=time(9, 15),
        )


def test_rejects_invalid_timezone_configuration() -> None:
    with pytest.raises(ValueError, match="timezone must not be empty"):
        FixedDailySessionCalendar(
            timezone="",
            open_time=time(9, 15),
            close_time=time(15, 30),
        )
    with pytest.raises(ValueError, match="unknown timezone"):
        FixedDailySessionCalendar(
            timezone="Not/AZone",
            open_time=time(9, 15),
            close_time=time(15, 30),
        )


def test_historical_timestamp_expectation_maps_open_and_closed() -> None:
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9, 15),
        close_time=time(15, 30),
    )

    assert (
        calendar.historical_timestamp_expected(
            datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
        )
        is True
    )
    assert (
        calendar.historical_timestamp_expected(
            datetime(2026, 8, 20, 16, 0, tzinfo=UTC)
        )
        is False
    )
