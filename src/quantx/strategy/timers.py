"""Deterministic, run-scoped storage for strategy timer requests.

This module validates and orders timer requests only. Event-driven dispatch and
timer consumption policy belong to the QX-08 driver integration phase.
"""

from __future__ import annotations

from datetime import UTC, datetime

from quantx.domain.strategy import TimerRequest
from quantx.domain.value_objects import InstrumentId


def _as_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _sort_key(request: TimerRequest) -> tuple[datetime, str]:
    return request.due_at.astimezone(UTC), request.timer_id


class TimerQueue:
    """Mutable registry scoped to one strategy run.

    Calling :meth:`due` is a read operation and does not consume requests.
    The caller explicitly acknowledges each dispatched request. Timer IDs
    remain reserved until the queue itself is discarded, even after
    acknowledgement, so a run cannot accidentally reuse an ID.
    """

    __slots__ = ("_pending", "_registered_ids")

    def __init__(self) -> None:
        self._pending: dict[str, TimerRequest] = {}
        self._registered_ids: set[str] = set()

    def register(
        self,
        request: TimerRequest,
        *,
        event_time: datetime,
        event_instrument: InstrumentId,
    ) -> None:
        """Register a request made at a market event, rejecting invalid state."""
        event_time_utc = _as_utc(event_time, name="event_time")
        due_at_utc = _as_utc(request.due_at, name="timer due_at")

        if request.instrument != event_instrument:
            raise ValueError("timer instrument must match registering event instrument")
        if due_at_utc <= event_time_utc:
            raise ValueError("timer due_at must be later than registering event time")
        if request.timer_id in self._registered_ids:
            raise ValueError("timer id must be unique within a run")

        self._pending[request.timer_id] = request
        self._registered_ids.add(request.timer_id)

    def due(self, as_of: datetime) -> tuple[TimerRequest, ...]:
        """Return due requests at an inclusive logical-time cut without consuming."""
        as_of_utc = _as_utc(as_of, name="as_of")
        return tuple(
            sorted(
                (
                    request
                    for request in self._pending.values()
                    if request.due_at.astimezone(UTC) <= as_of_utc
                ),
                key=_sort_key,
            )
        )

    def acknowledge(self, timer_id: str) -> None:
        """Consume one pending timer while keeping its ID reserved for this run."""
        if timer_id not in self._registered_ids:
            raise ValueError("timer id is not registered in this run")
        if timer_id not in self._pending:
            raise ValueError("timer id has already been acknowledged")
        del self._pending[timer_id]

    def pending(self) -> tuple[TimerRequest, ...]:
        """Return all unacknowledged requests in deterministic order."""
        return tuple(sorted(self._pending.values(), key=_sort_key))
