"""Immutable domain events for QuantX.

Events describe facts that have already happened. They are deliberately small
and framework-independent so the same event model can serve in-memory tests,
replay, persistence, WebSocket streaming, and future distributed transports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base event carrying identity and causality metadata."""

    event_id: str
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderCreated(DomainEvent):
    """Fact emitted after an order enters the local order ledger."""

    order_id: str = ""
    instrument_id: str = ""
    side: str = ""
    order_type: str = ""
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class OrderSubmitted(DomainEvent):
    """Fact emitted after an order is submitted to an execution venue."""

    order_id: str = ""
    venue: str = ""


@dataclass(frozen=True, slots=True)
class OrderFilled(DomainEvent):
    """Fact emitted when an execution fill is recorded."""

    order_id: str = ""
    fill_id: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class PositionUpdated(DomainEvent):
    """Fact emitted after a position ledger update."""

    instrument_id: str = ""
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class GenericDomainEvent(DomainEvent):
    """Extensible event for non-critical facts during early development."""

    event_type: str = ""
    data: Mapping[str, Any] | None = None
