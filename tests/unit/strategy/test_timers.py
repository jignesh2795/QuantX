from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from quantx.domain.strategy import (
    SignalAction,
    StrategyId,
    StrategyResult,
    StrategySignal,
    TimerRequest,
)
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.timers import TimerQueue

_EVENT_TIME = datetime(2026, 1, 1, tzinfo=UTC)
_INSTRUMENT = InstrumentId("NSE", "TCS")
_OTHER_INSTRUMENT = InstrumentId("NSE", "INFY")


def _request(
    timer_id: str,
    due_at: datetime,
    *,
    instrument: InstrumentId = _INSTRUMENT,
) -> TimerRequest:
    return TimerRequest(timer_id=timer_id, instrument=instrument, due_at=due_at)


def _signal() -> StrategySignal:
    return StrategySignal(
        strategy_id=StrategyId("timer-test"),
        strategy_version="1",
        instrument=_INSTRUMENT,
        action=SignalAction.HOLD,
        confidence=1.0,
        generated_at=_EVENT_TIME,
    )


def test_timer_request_rejects_empty_id_and_naive_due_at() -> None:
    for timer_id in ("", "   "):
        with pytest.raises(ValueError, match="timer id must not be empty"):
            _request(timer_id, _EVENT_TIME + timedelta(seconds=1))

    with pytest.raises(ValueError, match="timer due_at must be timezone-aware"):
        _request("timer-1", datetime(2026, 1, 1, 0, 0, 1))


def test_timer_request_is_immutable() -> None:
    request = _request("timer-1", _EVENT_TIME + timedelta(seconds=1))

    with pytest.raises(FrozenInstanceError):
        request.timer_id = "changed"  # type: ignore[misc]


def test_timer_queue_rejects_equal_or_past_due_at() -> None:
    queue = TimerQueue()
    for timer_id, due_at in (
        ("equal", _EVENT_TIME),
        ("past", _EVENT_TIME - timedelta(seconds=1)),
    ):
        with pytest.raises(ValueError, match="must be later"):
            queue.register(
                _request(timer_id, due_at),
                event_time=_EVENT_TIME,
                event_instrument=_INSTRUMENT,
            )

    assert queue.pending() == ()


def test_timer_queue_rejects_duplicate_timer_id() -> None:
    queue = TimerQueue()
    request = _request("timer-1", _EVENT_TIME + timedelta(seconds=1))
    queue.register(request, event_time=_EVENT_TIME, event_instrument=_INSTRUMENT)
    with pytest.raises(ValueError, match="unique within a run"):
        queue.register(
            _request("timer-1", _EVENT_TIME + timedelta(seconds=2)),
            event_time=_EVENT_TIME,
            event_instrument=_INSTRUMENT,
        )

    assert queue.pending() == (request,)


def test_timer_queue_rejects_id_reuse_after_acknowledgement() -> None:
    queue = TimerQueue()
    request = _request("timer-1", _EVENT_TIME + timedelta(seconds=1))
    queue.register(request, event_time=_EVENT_TIME, event_instrument=_INSTRUMENT)
    queue.acknowledge("timer-1")

    with pytest.raises(ValueError, match="unique within a run"):
        queue.register(
            _request("timer-1", _EVENT_TIME + timedelta(seconds=2)),
            event_time=_EVENT_TIME,
            event_instrument=_INSTRUMENT,
        )

    assert queue.pending() == ()


def test_timer_queue_rejects_foreign_instrument() -> None:
    queue = TimerQueue()

    with pytest.raises(ValueError, match="must match registering event instrument"):
        queue.register(
            _request(
                "timer-1",
                _EVENT_TIME + timedelta(seconds=1),
                instrument=_OTHER_INSTRUMENT,
            ),
            event_time=_EVENT_TIME,
            event_instrument=_INSTRUMENT,
        )

    assert queue.pending() == ()


def test_timer_queue_orders_by_due_instant_then_timer_id() -> None:
    queue = TimerQueue()
    same_instant_other_timezone = datetime(
        2026,
        1,
        1,
        5,
        30,
        10,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    later = _request("z-later-id", _EVENT_TIME + timedelta(seconds=10))
    same_instant = _request("a-earlier-id", same_instant_other_timezone)
    earlier = _request("m-earlier-time", _EVENT_TIME + timedelta(seconds=5))

    for request in (later, same_instant, earlier):
        queue.register(request, event_time=_EVENT_TIME, event_instrument=_INSTRUMENT)

    assert queue.pending() == (earlier, same_instant, later)


def test_timer_queue_due_is_inclusive_and_does_not_consume() -> None:
    queue = TimerQueue()
    due_now = _request("due-now", _EVENT_TIME + timedelta(seconds=5))
    due_later = _request("due-later", _EVENT_TIME + timedelta(seconds=10))
    for request in (due_later, due_now):
        queue.register(request, event_time=_EVENT_TIME, event_instrument=_INSTRUMENT)

    as_of_other_timezone = datetime(
        2026,
        1,
        1,
        5,
        30,
        5,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    assert queue.due(as_of_other_timezone) == (due_now,)
    assert queue.due(as_of_other_timezone) == (due_now,)
    assert queue.pending() == (due_now, due_later)


def test_timer_queue_acknowledge_removes_only_the_selected_timer() -> None:
    queue = TimerQueue()
    first = _request("first", _EVENT_TIME + timedelta(seconds=1))
    second = _request("second", _EVENT_TIME + timedelta(seconds=2))
    for request in (second, first):
        queue.register(request, event_time=_EVENT_TIME, event_instrument=_INSTRUMENT)

    queue.acknowledge("first")

    assert queue.pending() == (second,)
    assert queue.due(_EVENT_TIME + timedelta(seconds=2)) == (second,)


def test_timer_queue_rejects_unknown_or_already_acknowledged_id() -> None:
    queue = TimerQueue()
    with pytest.raises(ValueError, match="not registered"):
        queue.acknowledge("unknown")

    queue.register(
        _request("timer-1", _EVENT_TIME + timedelta(seconds=1)),
        event_time=_EVENT_TIME,
        event_instrument=_INSTRUMENT,
    )
    queue.acknowledge("timer-1")
    with pytest.raises(ValueError, match="already been acknowledged"):
        queue.acknowledge("timer-1")


def test_timer_queue_rejects_naive_event_time_and_as_of() -> None:
    queue = TimerQueue()
    request = _request("timer-1", _EVENT_TIME + timedelta(seconds=1))

    with pytest.raises(ValueError, match="event_time must be timezone-aware"):
        queue.register(
            request,
            event_time=datetime(2026, 1, 1),
            event_instrument=_INSTRUMENT,
        )
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        queue.due(datetime(2026, 1, 1))

    assert queue.pending() == ()


def test_strategy_result_timers_default_empty_and_positional_compat() -> None:
    signal = _signal()

    signal_only = StrategyResult(signal)
    signal_and_intent = StrategyResult(signal, None)
    timer = _request("timer-1", _EVENT_TIME + timedelta(seconds=1))
    explicit_timers = StrategyResult(signal, None, (timer,))

    assert signal_only.timers == ()
    assert signal_and_intent.intent is None
    assert signal_and_intent.timers == ()
    assert explicit_timers.timers == (timer,)
