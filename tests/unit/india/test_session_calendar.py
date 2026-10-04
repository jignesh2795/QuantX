from datetime import UTC, date, datetime, time
from types import SimpleNamespace

import pytest

from quantx.domain.clock import FixedClock
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.session_calendar import (
    IndiaSessionCalendar,
    IndiaSessionCalendarSnapshot,
    IndiaSessionEvaluator,
    IndiaSessionDayOverride,
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionWindow,
)

IST = "Asia/Kolkata"
SUBMIT = IndiaSessionPermission.ORDER_SUBMISSION
CANCEL = IndiaSessionPermission.ORDER_CANCELLATION


def _window(
    session_id: str,
    start: tuple[int, int],
    end: tuple[int, int],
    *permissions: IndiaSessionPermission,
) -> IndiaSessionWindow:
    return IndiaSessionWindow(
        session_id=session_id,
        start=time(*start),
        end=time(*end),
        permissions=frozenset(permissions or (SUBMIT,)),
    )


REGULAR = _window("regular", (9, 15), (15, 30), SUBMIT)


def _calendar_snapshot(**overrides):
    values = dict(
        version="v1",
        provenance="p1",
        timezone=IST,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
        valid_from=date(2026, 1, 1),
        valid_through=date(2026, 12, 31),
        windows_by_weekday=(),
    )
    values.update(overrides)
    return IndiaSessionCalendarSnapshot(**values)


def _calendar(
    *,
    windows_by_weekday=(
        (0, (REGULAR,)),
        (1, (REGULAR,)),
        (2, (REGULAR,)),
        (3, (REGULAR,)),
        (4, (REGULAR,)),
    ),
    holidays=frozenset(),
    overrides=(),
    valid_from=date(2026, 1, 1),
    valid_through=date(2026, 12, 31),
) -> IndiaSessionCalendar:
    return IndiaSessionCalendar(
        IndiaSessionCalendarSnapshot(
            version="india-calendar-test-v1",
            provenance="test-fixture",
            timezone=IST,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            valid_from=valid_from,
            valid_through=valid_through,
            windows_by_weekday=windows_by_weekday,
            holidays=holidays,
            overrides=overrides,
        )
    )


def _at_ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


def test_regular_session_allows_order_submission() -> None:
    result = _calendar().evaluate(_at_ist(5, 5, 0), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.ALLOW
    assert result.session_id == "regular"
    assert result.calendar_version == "india-calendar-test-v1"
    assert result.provenance == "test-fixture"
    assert result.calendar_evaluated is True


def test_closed_time_blocks() -> None:
    result = _calendar().evaluate(_at_ist(5, 11, 0), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "closed" in result.reason


def test_weekend_blocks_without_becoming_unknown() -> None:
    result = _calendar().evaluate(_at_ist(4, 5, 0), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "closed" in result.reason


def test_explicit_holiday_blocks() -> None:
    result = _calendar(
        holidays=frozenset({date(2026, 1, 5)}),
    ).evaluate(_at_ist(5, 5, 0), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "holiday" in result.reason


def test_partial_day_override_replaces_weekly_schedule() -> None:
    result = _calendar(
        overrides=(
            IndiaSessionDayOverride(
                date(2026, 1, 5),
                (_window("partial", (9, 15), (12, 0), SUBMIT),),
            ),
        ),
    ).evaluate(_at_ist(5, 12, 30), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK


def test_special_override_can_open_a_holiday() -> None:
    opened = _calendar(
        holidays=frozenset({date(2026, 1, 5)}),
        overrides=(
            IndiaSessionDayOverride(
                date(2026, 1, 5),
                (_window("muhurat", (18, 0), (19, 0), SUBMIT),),
            ),
        ),
    ).evaluate(
        datetime(2026, 1, 5, 12, 30, tzinfo=UTC),
        permission=SUBMIT,
    )
    assert opened.decision is IndiaSessionDecision.ALLOW
    assert opened.session_id == "muhurat"


def test_session_permission_can_deny_submission_inside_open_session() -> None:
    result = _calendar(
        overrides=(
            IndiaSessionDayOverride(
                date(2026, 1, 5),
                (_window("cancel-only", (9, 0), (9, 30), CANCEL),),
            ),
        ),
    ).evaluate(datetime(2026, 1, 5, 3, 45, tzinfo=UTC), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "PERMISSION" in result.reason


def test_midnight_crossing_session_is_active_before_and_after_midnight() -> None:
    overnight = _window("overnight", (17, 0), (1, 0), SUBMIT)
    calendar = _calendar(
        windows_by_weekday=(
            (0, (overnight,)),
            (1, (overnight,)),
            (2, (overnight,)),
            (3, (overnight,)),
            (4, (overnight,)),
        ),
    )

    before = calendar.evaluate(
        datetime(2026, 1, 5, 17, 0, tzinfo=UTC),
        permission=SUBMIT,
    )
    after = calendar.evaluate(
        datetime(2026, 1, 5, 19, 0, tzinfo=UTC),
        permission=SUBMIT,
    )

    assert before.decision is IndiaSessionDecision.ALLOW
    assert after.decision is IndiaSessionDecision.ALLOW
    assert before.session_id == after.session_id == "overnight"


def test_unknown_calendar_coverage_blocks_fail_closed() -> None:
    result = _calendar(
        valid_from=date(2026, 1, 5),
        valid_through=date(2026, 1, 9),
    ).evaluate(datetime(2026, 1, 10, 5, 0, tzinfo=UTC), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "DATA_UNAVAILABLE" in result.reason
    assert result.calendar_evaluated is True


def test_naive_evaluation_timestamp_blocks_fail_closed() -> None:
    result = _calendar().evaluate(datetime(2026, 1, 5, 10, 0), permission=SUBMIT)
    assert result.decision is IndiaSessionDecision.BLOCK
    assert "DATA_UNAVAILABLE" in result.reason


def test_clock_backed_evaluator_allows_matching_scope() -> None:
    calendar = _calendar()
    evaluator = IndiaSessionEvaluator(
        calendar,
        FixedClock(datetime(2026, 1, 5, 5, 0, tzinfo=UTC)),
    )
    request = SimpleNamespace(
        execution_context=SimpleNamespace(
            market=MarketContext(
                MarketRegion.INDIA,
                MarketFamily.EQUITY,
                "NSE",
                "IN",
            )
        )
    )

    result = evaluator(request)

    assert result.decision is IndiaSessionDecision.ALLOW
    assert result.exchange is IndianExchange.NSE
    assert result.segment is IndianSegment.EQUITY


def test_clock_backed_evaluator_blocks_mismatched_scope() -> None:
    calendar = _calendar()
    evaluator = IndiaSessionEvaluator(
        calendar,
        FixedClock(datetime(2026, 1, 5, 5, 0, tzinfo=UTC)),
    )
    request = SimpleNamespace(
        execution_context=SimpleNamespace(
            market=MarketContext(
                MarketRegion.INDIA,
                MarketFamily.EQUITY,
                "BSE",
                "IN",
            )
        )
    )

    result = evaluator(request)

    assert result.decision is IndiaSessionDecision.BLOCK
    assert "SCOPE_MISMATCH" in result.reason


def test_calendar_evaluation_is_deterministic() -> None:
    calendar = _calendar()
    timestamp = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)
    first = calendar.evaluate(timestamp, permission=SUBMIT)
    second = calendar.evaluate(timestamp, permission=SUBMIT)
    assert first == second


def test_blank_version_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        _calendar_snapshot(version=" ")


def test_blank_provenance_rejected() -> None:
    with pytest.raises(ValueError, match="provenance"):
        _calendar_snapshot(provenance=" ")


def test_invalid_timezone_rejected() -> None:
    with pytest.raises(Exception, match="No time zone found"):
        _calendar_snapshot(timezone="Not/AZone")


def test_invalid_calendar_range_rejected() -> None:
    with pytest.raises(ValueError, match="ordered"):
        _calendar_snapshot(
            valid_from=date(2026, 1, 2),
            valid_through=date(2026, 1, 1),
        )
