"""Synchronous in-process event bus for the v0.1 modular monolith."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from .events import DomainEvent

EventT = TypeVar("EventT", bound=DomainEvent)
Handler = Callable[[DomainEvent], None]


class EventBus:
    """Minimal publish/subscribe bus.

    The implementation is deliberately in-process for v0.1. A transport port
    can replace it later with Redis, NATS, ZeroMQ, or another message system
    without changing the domain event contract.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[EventT], handler: Callable[[EventT], None]) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def publish(self, event: DomainEvent) -> None:
        """Synchronously publish an event to registered handlers."""
        for handler in tuple(self._handlers.get(type(event), ())):
            handler(event)

    def clear(self) -> None:
        """Remove all handlers, primarily for test isolation."""
        self._handlers.clear()
