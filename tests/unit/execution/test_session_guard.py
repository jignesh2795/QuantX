from datetime import UTC, datetime, time

from quantx.domain.clock import FixedClock
from quantx.domain.deployment import ExecutionMode
from quantx.domain.sessions import (
    SessionState,
    SessionWindow,
    TradingSession,
    TradingSessionSchedule,
)
from quantx.execution.session_guard import SessionExecutionGuard


def _session(hour: int) -> TradingSession:
    schedule = TradingSessionSchedule(
        timezone="Asia/Kolkata",
        windows_by_weekday=tuple(
            (day, (SessionWindow(time(9, 15), time(15, 30)),)) for day in range(5)
        ),
    )
    return TradingSession(
        schedule=schedule,
        clock=FixedClock(datetime(2026, 9, 28, hour, 0, tzinfo=UTC)),
    )


def test_indian_session_opens_and_closes_by_local_time() -> None:
    open_session = _session(6)  # 11:30 IST
    assert open_session.status().state is SessionState.OPEN

    closed_session = _session(11)  # 16:30 IST
    assert closed_session.status().state is SessionState.CLOSED


def test_weekend_is_closed() -> None:
    schedule = TradingSessionSchedule(
        timezone="Asia/Kolkata",
        windows_by_weekday=((0, (SessionWindow(time(9, 15), time(15, 30)),)),),
    )
    session = TradingSession(
        schedule=schedule,
        clock=FixedClock(datetime(2026, 9, 27, 6, 0, tzinfo=UTC)),
    )
    assert session.status().open is False


def test_replay_is_not_blocked_by_live_session() -> None:
    guard = SessionExecutionGuard(_session(11))
    assert guard.check(ExecutionMode.REPLAY).allowed


def test_paper_is_blocked_when_session_is_closed() -> None:
    guard = SessionExecutionGuard(_session(11))
    result = guard.check(ExecutionMode.PAPER)
    assert not result.allowed
    assert "closed" in result.reason
