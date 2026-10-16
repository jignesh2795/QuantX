"""Run-scoped one-shot timer validation and deterministic due-list management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from quantx.domain.market_data import MarketDataEvent
from quantx.domain.strategy import StrategyResult, TimerRequest
from quantx.domain.value_objects import InstrumentId


def validate_timer_requests(
    result: StrategyResult,
    event: MarketDataEvent,
    *,
    previously_registered: frozenset[str] = frozenset(),
) -> None:
    """Validate a whole timer batch before any timer is registered."""
    if not isinstance(result.timers, tuple):
        raise TypeError("strategy result timers must be an immutable tuple")
    seen: set[str] = set()
    event_time = event.timestamp.astimezone(UTC)
    for timer in result.timers:
        if not isinstance(timer, TimerRequest):
            raise TypeError("strategy result timers must contain TimerRequest values")
        if timer.timer_id in previously_registered or timer.timer_id in seen:
            raise ValueError(f"timer_id must be unique for the strategy run: {timer.timer_id}")
        if timer.instrument != event.instrument:
            raise ValueError("timer instrument must match the registering event instrument")
        if timer.due_at.astimezone(UTC) <= event_time:
            raise ValueError("timer due_at must be strictly later than the registering event")
        seen.add(timer.timer_id)


@dataclass(frozen=True, slots=True)
class TimerInvocation:
    """Immutable facts describing one timer as it is delivered to a strategy."""

    timer_id: str
    instrument: InstrumentId
    due_at: datetime
    registered_at: datetime
    registration_sequence: int

    def __post_init__(self) -> None:
        if not self.timer_id.strip():
            raise ValueError("timer_id must not be empty")
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValueError("timer due_at must be timezone-aware")
        if self.registered_at.tzinfo is None or self.registered_at.utcoffset() is None:
            raise ValueError("timer registered_at must be timezone-aware")
        if isinstance(self.registration_sequence, bool) or self.registration_sequence < 0:
            raise ValueError("registration_sequence must be non-negative")
        due_at = self.due_at.astimezone(UTC)
        registered_at = self.registered_at.astimezone(UTC)
        if due_at <= registered_at:
            raise ValueError("timer due_at must be strictly later than registered_at")
        object.__setattr__(self, "due_at", due_at)
        object.__setattr__(self, "registered_at", registered_at)


@dataclass(frozen=True, slots=True)
class UndeliveredTimer:
    """A registered timer left pending because the run ended or halted."""

    timer: TimerInvocation
    reason: str


@dataclass(slots=True)
class TimerRegistry:
    """Per-run due list. Fired IDs remain reserved to prevent timer reuse."""

    _pending: dict[str, TimerInvocation] = field(default_factory=dict, init=False)
    _registered_ids: set[str] = field(default_factory=set, init=False)
    _next_sequence: int = field(default=0, init=False)

    def register_result(
        self,
        result: StrategyResult,
        event: MarketDataEvent,
    ) -> tuple[TimerInvocation, ...]:
        """Validate atomically, then register the timer requests in result order."""
        validate_timer_requests(
            result,
            event,
            previously_registered=frozenset(self._registered_ids),
        )
        registered: list[TimerInvocation] = []
        event_time = event.timestamp.astimezone(UTC)
        for request in result.timers:
            invocation = TimerInvocation(
                timer_id=request.timer_id,
                instrument=request.instrument,
                due_at=request.due_at,
                registered_at=event_time,
                registration_sequence=self._next_sequence,
            )
            self._next_sequence += 1
            self._registered_ids.add(request.timer_id)
            self._pending[request.timer_id] = invocation
            registered.append(invocation)
        return tuple(registered)

    def take_due(self, through_time: datetime) -> tuple[TimerInvocation, ...]:
        """Consume every timer due by through_time in normative deterministic order."""
        if through_time.tzinfo is None or through_time.utcoffset() is None:
            raise ValueError("timer dispatch time must be timezone-aware")
        cutoff = through_time.astimezone(UTC)
        due = tuple(
            sorted(
                (timer for timer in self._pending.values() if timer.due_at <= cutoff),
                key=lambda timer: (timer.due_at, timer.timer_id),
            )
        )
        for timer in due:
            del self._pending[timer.timer_id]
        return due

    @property
    def pending(self) -> tuple[TimerInvocation, ...]:
        """Pending timers in the same order used for delivery."""
        return tuple(
            sorted(
                self._pending.values(),
                key=lambda timer: (timer.due_at, timer.timer_id),
            )
        )

    def record_undelivered(self, reason: str) -> tuple[UndeliveredTimer, ...]:
        if not reason.strip():
            raise ValueError("undelivered timer reason must not be empty")
        records = tuple(UndeliveredTimer(timer, reason) for timer in self.pending)
        self._pending.clear()
        return records
