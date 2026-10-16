"""Deterministic one-shot timer registration and due-list tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import (
    SignalAction,
    StrategyDefinition,
    StrategyId,
    StrategyResult,
    StrategySignal,
    TimerRequest,
)
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.runtime import StrategyRuntime
from quantx.strategy.timers import TimerRegistry


def _event(timestamp: datetime, instrument: InstrumentId | None = None) -> MarketDataEvent:
    selected = instrument or InstrumentId("NSE", "TCS")
    quote = Quote(selected, timestamp, bid=None, ask=None, last=None)
    return MarketDataEvent(MarketDataType.QUOTE, timestamp, selected, quote)


def _ir():
    return StrategyCompiler.compile(StrategyDefinition(StrategyId("timer-test"), "1", "Timer test"))


def _result(
    timestamp: datetime,
    instrument: InstrumentId,
    *timers: TimerRequest,
) -> StrategyResult:
    return StrategyResult(
        signal=StrategySignal(
            StrategyId("timer-test"),
            "1",
            instrument,
            SignalAction.HOLD,
            1.0,
            generated_at=timestamp,
        ),
        timers=tuple(timers),
    )


def test_timer_request_requires_nonempty_id_and_aware_due_time() -> None:
    due_at = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    instrument = InstrumentId("NSE", "TCS")

    with pytest.raises(ValueError, match="timer_id"):
        TimerRequest(" ", instrument, due_at)
    with pytest.raises(ValueError, match="timezone-aware"):
        TimerRequest("timer-1", instrument, datetime(2026, 1, 1, 9, 16))


@pytest.mark.parametrize("offset_seconds", [0, -1])
def test_timer_request_rejects_equal_or_past_due_at(offset_seconds: int) -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    request = TimerRequest(
        "timer-1", event.instrument, event_time + timedelta(seconds=offset_seconds)
    )

    with pytest.raises(ValueError, match="strictly later"):
        TimerRegistry().register_result(_result(event_time, event.instrument, request), event)


def test_timer_registry_rejects_cross_instrument_timer() -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    request = TimerRequest(
        "timer-1", InstrumentId("NSE", "INFY"), event_time + timedelta(minutes=1)
    )

    with pytest.raises(ValueError, match="match the registering event"):
        TimerRegistry().register_result(_result(event_time, event.instrument, request), event)


def test_timer_dispatch_orders_by_due_at_then_timer_id() -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    later = TimerRequest("timer-z", event.instrument, event_time + timedelta(minutes=2))
    same_a = TimerRequest("timer-a", event.instrument, event_time + timedelta(minutes=1))
    same_b = TimerRequest("timer-b", event.instrument, event_time + timedelta(minutes=1))
    registry = TimerRegistry()
    registry.register_result(_result(event_time, event.instrument, later, same_b, same_a), event)

    due = registry.take_due(event_time + timedelta(minutes=1))

    assert tuple(item.timer_id for item in due) == ("timer-a", "timer-b")
    assert tuple(item.timer_id for item in registry.pending) == ("timer-z",)
    assert registry.take_due(event_time + timedelta(minutes=2))[0].timer_id == "timer-z"
    assert registry.take_due(event_time + timedelta(minutes=3)) == ()


def test_timer_registration_is_atomic_and_ids_cannot_be_reused_after_firing() -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    registry = TimerRegistry()
    first = TimerRequest("timer-1", event.instrument, event_time + timedelta(minutes=1))
    registry.register_result(_result(event_time, event.instrument, first), event)
    registry.take_due(event_time + timedelta(minutes=1))

    new_request = TimerRequest("timer-2", event.instrument, event_time + timedelta(minutes=2))
    reused = TimerRequest("timer-1", event.instrument, event_time + timedelta(minutes=3))
    with pytest.raises(ValueError, match="unique"):
        registry.register_result(_result(event_time, event.instrument, new_request, reused), event)
    assert registry.pending == ()


def test_timer_after_replay_horizon_is_reported_pending() -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    request = TimerRequest("timer-1", event.instrument, event_time + timedelta(minutes=5))
    registry = TimerRegistry()
    registry.register_result(_result(event_time, event.instrument, request), event)

    undelivered = registry.record_undelivered("run ended before the timer became due")

    assert len(undelivered) == 1
    assert undelivered[0].timer.timer_id == "timer-1"
    assert "run ended" in undelivered[0].reason
    assert registry.pending == ()


def test_strategy_runtime_rejects_invalid_timer_request_before_returning_result() -> None:
    event_time = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    event = _event(event_time)
    ir = _ir()

    class _BadTimerStrategy:
        def on_market_data(self, context):
            assert context.event is not None
            return StrategyResult(
                StrategySignal(
                    ir.strategy_id,
                    ir.version,
                    context.event.instrument,
                    SignalAction.HOLD,
                    1.0,
                    generated_at=context.event.timestamp,
                ),
                timers=(
                    TimerRequest("timer-1", context.event.instrument, context.event.timestamp),
                ),
            )

    with pytest.raises(ValueError, match="strictly later"):
        StrategyRuntime(_BadTimerStrategy()).evaluate(event, ir)
