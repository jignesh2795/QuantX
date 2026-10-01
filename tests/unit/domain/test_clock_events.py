from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.clock import FixedClock
from quantx.domain.event_bus import EventBus
from quantx.domain.events import GenericDomainEvent, OrderFilled


def test_fixed_clock_normalizes_to_utc() -> None:
    clock = FixedClock(datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc))
    assert clock.now() == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def test_fixed_clock_rejects_naive_datetime() -> None:
    try:
        FixedClock(datetime(2026, 1, 1, 10, 0))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_event_bus_dispatches_to_matching_event_type() -> None:
    bus = EventBus()
    received: list[OrderFilled] = []
    bus.subscribe(OrderFilled, received.append)

    event = OrderFilled(
        event_id="evt-1",
        occurred_at=datetime.now(timezone.utc),
        correlation_id="corr-1",
        order_id="ord-1",
        fill_id="fill-1",
        quantity=Decimal("2"),
        price=Decimal("100.25"),
    )
    bus.publish(event)

    assert received == [event]


def test_event_bus_does_not_cross_dispatch_event_types() -> None:
    bus = EventBus()
    received: list[OrderFilled] = []
    bus.subscribe(OrderFilled, received.append)

    event = GenericDomainEvent(
        event_id="evt-2",
        occurred_at=datetime.now(timezone.utc),
        correlation_id="corr-2",
        event_type="test",
    )
    bus.publish(event)

    assert received == []
