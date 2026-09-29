"""Explicit market-session state and execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from .clock import Clock


class SessionState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("session window must have start before end")


@dataclass(frozen=True, slots=True)
class TradingSessionSchedule:
    timezone: str
    windows_by_weekday: tuple[tuple[int, tuple[SessionWindow, ...]], ...]

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        weekdays = [day for day, _ in self.windows_by_weekday]
        if len(set(weekdays)) != len(weekdays) or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("weekdays must be unique values from 0 through 6")

    def state_at(self, timestamp: datetime) -> SessionState:
        local = timestamp.astimezone(ZoneInfo(self.timezone))
        for weekday, windows in self.windows_by_weekday:
            if weekday == local.weekday() and any(
                window.start <= local.time() < window.end for window in windows
            ):
                return SessionState.OPEN
        return SessionState.CLOSED


@dataclass(frozen=True, slots=True)
class TradingSessionStatus:
    state: SessionState
    observed_at: datetime
    timezone: str

    @property
    def open(self) -> bool:
        return self.state is SessionState.OPEN


class TradingSession:
    """Clock-backed session evaluator with deterministic simulation support."""

    def __init__(self, *, schedule: TradingSessionSchedule, clock: Clock) -> None:
        self._schedule = schedule
        self._clock = clock

    def status(self) -> TradingSessionStatus:
        now = self._clock.now()
        return TradingSessionStatus(
            self._schedule.state_at(now),
            now,
            self._schedule.timezone,
        )
