"""Deterministic India trading-session and calendar boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from quantx.domain.clock import Clock
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketFamily

from .domain import IndianExchange, IndianSegment


class IndiaSessionPermission(StrEnum):
    """Operations a venue session may permit."""

    ORDER_SUBMISSION = "ORDER_SUBMISSION"
    ORDER_MODIFICATION = "ORDER_MODIFICATION"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"


class IndiaSessionDecision(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class IndiaSessionWindow:
    """A named session window in the calendar timezone.

    An end earlier than start represents a session crossing local midnight.
    """

    session_id: str
    start: time
    end: time
    permissions: frozenset[IndiaSessionPermission]

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be blank")
        if self.start == self.end:
            raise ValueError("session window cannot have identical start and end")
        if not self.permissions:
            raise ValueError("session window must grant at least one permission")

    @property
    def crosses_midnight(self) -> bool:
        return self.end < self.start

    def contains(self, local_time: time) -> bool:
        if self.crosses_midnight:
            return local_time >= self.start or local_time < self.end
        return self.start <= local_time < self.end


@dataclass(frozen=True, slots=True)
class IndiaSessionDayOverride:
    """Date-specific replacement for the recurring weekly schedule."""

    trading_date: date
    windows: tuple[IndiaSessionWindow, ...]


@dataclass(frozen=True, slots=True)
class IndiaSessionCalendarSnapshot:
    """Versioned, provenance-carrying India session/calendar data.

    Holidays are explicit closures unless a date override supplies special
    session windows. This supports partial trading days and special sessions
    such as Muhurat without treating them as normal weekdays.
    """

    version: str
    provenance: str
    timezone: str
    exchange: IndianExchange
    segment: IndianSegment
    valid_from: date
    valid_through: date
    windows_by_weekday: tuple[tuple[int, tuple[IndiaSessionWindow, ...]], ...]
    holidays: frozenset[date] = frozenset()
    overrides: tuple[IndiaSessionDayOverride, ...] = ()

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("calendar version must not be blank")
        if not self.provenance.strip():
            raise ValueError("calendar provenance must not be blank")
        ZoneInfo(self.timezone)
        if self.valid_through < self.valid_from:
            raise ValueError("calendar validity range must be ordered")

        weekdays = [day for day, _ in self.windows_by_weekday]
        if len(set(weekdays)) != len(weekdays) or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("weekdays must be unique values from 0 through 6")

        override_dates = [item.trading_date for item in self.overrides]
        if len(set(override_dates)) != len(override_dates):
            raise ValueError("calendar overrides must have unique dates")

        covered_dates = set(self.holidays) | set(override_dates)
        for candidate in covered_dates:
            if not self.valid_from <= candidate <= self.valid_through:
                raise ValueError("holiday/override date must be inside calendar validity")

    def known_on(self, trading_date: date) -> bool:
        return self.valid_from <= trading_date <= self.valid_through

    def windows_for(self, trading_date: date) -> tuple[IndiaSessionWindow, ...]:
        for override in self.overrides:
            if override.trading_date == trading_date:
                return override.windows
        if trading_date in self.holidays:
            return ()
        for weekday, windows in self.windows_by_weekday:
            if weekday == trading_date.weekday():
                return windows
        return ()


@dataclass(frozen=True, slots=True)
class IndiaSessionResult:
    """Point-in-time result of the India session/calendar boundary."""

    decision: IndiaSessionDecision
    reason: str
    calendar_version: str
    provenance: str
    evaluated_at: datetime
    exchange: IndianExchange
    segment: IndianSegment
    session_id: str | None = None
    granted_permissions: frozenset[IndiaSessionPermission] = frozenset()
    calendar_evaluated: bool = False


class IndiaSessionEvaluator:
    """Clock-backed callable adapter for the India LIVE session boundary."""

    def __init__(self, calendar: IndiaSessionCalendar, clock: Clock) -> None:
        self._calendar = calendar
        self._clock = clock

    def __call__(self, request: ApprovedExecutionRequest) -> IndiaSessionResult:
        market = request.execution_context.market
        segment = {
            MarketFamily.EQUITY: IndianSegment.EQUITY,
            MarketFamily.DERIVATIVES: IndianSegment.DERIVATIVES,
            MarketFamily.FX: IndianSegment.CURRENCY,
            MarketFamily.COMMODITIES: IndianSegment.COMMODITY,
        }.get(market.family)
        now = self._clock.now()
        if market.venue != self._calendar.exchange.value:
            return self._calendar.blocked(
                now,
                "INDIA_SESSION_SCOPE_MISMATCH: calendar exchange does not match request market",
            )
        if segment is not self._calendar.segment:
            return self._calendar.blocked(
                now,
                "INDIA_SESSION_SCOPE_MISMATCH: calendar segment does not match request market",
            )
        return self._calendar.evaluate(
            now,
            permission=IndiaSessionPermission.ORDER_SUBMISSION,
        )


class IndiaSessionCalendar:
    """Evaluate India session permissions deterministically."""

    def __init__(self, snapshot: IndiaSessionCalendarSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def exchange(self) -> IndianExchange:
        return self._snapshot.exchange

    @property
    def segment(self) -> IndianSegment:
        return self._snapshot.segment

    def blocked(
        self,
        evaluated_at: datetime,
        reason: str,
        *,
        session_id: str | None = None,
        granted_permissions: frozenset[IndiaSessionPermission] = frozenset(),
    ) -> IndiaSessionResult:
        return self._blocked(
            evaluated_at,
            reason,
            session_id=session_id,
            granted_permissions=granted_permissions,
        )

    def evaluate(
        self,
        evaluated_at: datetime,
        *,
        permission: IndiaSessionPermission,
    ) -> IndiaSessionResult:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            return self._blocked(
                evaluated_at,
                "INDIA_SESSION_DATA_UNAVAILABLE: evaluation timestamp must be aware",
            )

        local = evaluated_at.astimezone(ZoneInfo(self._snapshot.timezone))
        local_date = local.date()
        previous_date = local_date - timedelta(days=1)

        if not self._snapshot.known_on(local_date):
            return self._blocked(
                evaluated_at,
                "INDIA_SESSION_DATA_UNAVAILABLE: calendar coverage is unknown",
            )

        current_windows = self._snapshot.windows_for(local_date)
        current_active = [
            window
            for window in current_windows
            if permission in window.permissions
            and (
                window.contains(local.time())
                and (not window.crosses_midnight or local.time() >= window.start)
            )
        ]
        active = current_active
        if active:
            window = active[0]
            return IndiaSessionResult(
                IndiaSessionDecision.ALLOW,
                f"india session {window.session_id} permits {permission.value}",
                self._snapshot.version,
                self._snapshot.provenance,
                evaluated_at,
                self._snapshot.exchange,
                self._snapshot.segment,
                window.session_id,
                window.permissions,
                True,
            )

        active_any = [
            window
            for window in current_windows
            if window.contains(local.time())
            and (not window.crosses_midnight or local.time() >= window.start)
        ]

        if self._snapshot.known_on(previous_date):
            previous_windows = self._snapshot.windows_for(previous_date)
            active_previous = [
                window
                for window in previous_windows
                if window.crosses_midnight
                and local.time() < window.end
                and permission in window.permissions
            ]
            if active_previous:
                window = active_previous[0]
                return IndiaSessionResult(
                    IndiaSessionDecision.ALLOW,
                    f"india session {window.session_id} permits {permission.value}",
                    self._snapshot.version,
                    self._snapshot.provenance,
                    evaluated_at,
                    self._snapshot.exchange,
                    self._snapshot.segment,
                    window.session_id,
                    window.permissions,
                    True,
                )
            active_any.extend(
                window
                for window in previous_windows
                if window.crosses_midnight and local.time() < window.end
            )

        if active_any:
            window = active_any[0]
            return self._blocked(
                evaluated_at,
                f"INDIA_SESSION_PERMISSION_BLOCKED: session {window.session_id} "
                f"does not permit {permission.value}",
                session_id=window.session_id,
                granted_permissions=window.permissions,
            )

        if local_date in self._snapshot.holidays and not current_windows:
            reason = "india trading calendar holiday"
        else:
            reason = "india trading session is closed"
        return self._blocked(evaluated_at, reason)

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None:
        """Return whether historical market data is expected at the timestamp.

        This checks session windows and calendar coverage only. It does not
        depend on order-submission permissions, so research gap detection does
        not inherit LIVE execution policy.
        """

        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")

        local = timestamp.astimezone(ZoneInfo(self._snapshot.timezone))
        local_date = local.date()
        local_time = local.time()
        previous_date = local_date - timedelta(days=1)

        if not self._snapshot.known_on(local_date):
            return None

        current_windows = self._snapshot.windows_for(local_date)
        if any(
            window.contains(local_time)
            and (not window.crosses_midnight or local_time >= window.start)
            for window in current_windows
        ):
            return True

        if self._snapshot.known_on(previous_date):
            previous_windows = self._snapshot.windows_for(previous_date)
            if any(
                window.crosses_midnight
                and local_time < window.end
                for window in previous_windows
            ):
                return True

        return False

    def _blocked(
        self,
        evaluated_at: datetime,
        reason: str,
        *,
        session_id: str | None = None,
        granted_permissions: frozenset[IndiaSessionPermission] = frozenset(),
    ) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.BLOCK,
            reason,
            self._snapshot.version,
            self._snapshot.provenance,
            evaluated_at,
            self._snapshot.exchange,
            self._snapshot.segment,
            session_id,
            granted_permissions,
            True,
        )


__all__ = [
    "IndiaSessionCalendar",
    "IndiaSessionCalendarSnapshot",
    "IndiaSessionDayOverride",
    "IndiaSessionDecision",
    "IndiaSessionEvaluator",
    "IndiaSessionPermission",
    "IndiaSessionResult",
    "IndiaSessionWindow",
]
