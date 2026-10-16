"""Observe-only callback delivery order and fault-containment tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.orders import Fill
from quantx.domain.strategy import StrategyDefinition, StrategyId, StrategySignal, SignalAction
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.callbacks import (
    OrderUpdateFact,
    dispatch_post_commit_callbacks,
    dispatch_timer_callback,
)
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.timers import TimerInvocation


def _ir():
    return StrategyCompiler.compile(StrategyDefinition(StrategyId("callbacks"), "1", "Callbacks"))


def _event(at: datetime) -> MarketDataEvent:
    instrument = InstrumentId("NSE", "TCS")
    return MarketDataEvent(
        MarketDataType.QUOTE,
        at,
        instrument,
        Quote(instrument, at, last=Decimal("100")),
    )


def _fill(at: datetime) -> Fill:
    return Fill(
        uuid4(),
        InstrumentId("NSE", "TCS"),
        OrderSide.BUY,
        Decimal("1"),
        Decimal("100"),
        filled_at=at,
    )


def _order_update(at: datetime) -> OrderUpdateFact:
    return OrderUpdateFact(
        client_order_id="order-1",
        instrument=InstrumentId("NSE", "TCS"),
        status=OrderStatus.PARTIALLY_FILLED,
        order_quantity=Decimal("2"),
        filled_quantity=Decimal("1"),
        remaining_quantity=Decimal("1"),
        created_at=at,
        evidence_time=at,
    )


def test_post_commit_dispatch_attempts_all_fills_then_order_update() -> None:
    at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    context = StrategyContext(_event(at), _ir(), as_of=at)
    calls: list[tuple[str, StrategyContext, object]] = []

    class _Observers:
        def on_fill(self, callback_context, fill):
            calls.append(("on_fill", callback_context, fill))
            raise RuntimeError(f"fill notification failed {fill.execution_id}")

        def on_order_update(self, callback_context, update):
            calls.append(("on_order_update", callback_context, update))
            raise ValueError("order notification failed")

    fills = (_fill(at), _fill(at + timedelta(microseconds=1)))
    faults = dispatch_post_commit_callbacks(_Observers(), context, fills, _order_update(at))

    assert tuple(call[0] for call in calls) == ("on_fill", "on_fill", "on_order_update")
    assert all(call[1] is context for call in calls)
    assert len(faults) == 3
    assert tuple(fault.callback_name for fault in faults) == (
        "on_fill", "on_fill", "on_order_update"
    )
    assert tuple(fault.exception_type for fault in faults) == (
        "RuntimeError", "RuntimeError", "ValueError"
    )
    assert all(not hasattr(fault, "traceback") for fault in faults)


def test_timer_callback_receives_eventless_context_at_due_time() -> None:
    due_at = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
    timer = TimerInvocation(
        "timer-1",
        InstrumentId("NSE", "TCS"),
        due_at,
        due_at - timedelta(minutes=1),
        0,
    )
    context = StrategyContext(None, _ir(), as_of=due_at)
    seen: list[tuple[StrategyContext, TimerInvocation]] = []

    class _Observer:
        def on_timer(self, callback_context, invocation):
            seen.append((callback_context, invocation))

    fault = dispatch_timer_callback(_Observer(), context, timer)

    assert fault is None
    assert seen == [(context, timer)]
    assert seen[0][0].event is None
    assert seen[0][0].as_of == due_at


def test_observer_must_be_observe_only_and_return_none() -> None:
    at = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    context = StrategyContext(_event(at), _ir(), as_of=at)

    class _BadObserver:
        def on_fill(self, callback_context, fill):
            return object()

    fault = dispatch_post_commit_callbacks(
        _BadObserver(), context, (_fill(at),), _order_update(at)
    )

    assert len(fault) == 1
    assert fault[0].callback_name == "on_fill"
    assert fault[0].exception_type == "TypeError"
    assert "must return None" in fault[0].message
