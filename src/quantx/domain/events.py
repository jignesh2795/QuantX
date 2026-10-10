"""Immutable domain events for QuantX."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: str
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")

    @property
    def event_type(self) -> str:
        return type(self).__name__


@dataclass(frozen=True, slots=True)
class OrderCreated(DomainEvent):
    order_id: str = ""
    instrument_id: str = ""
    side: str = ""
    order_type: str = ""
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class OrderSubmitted(DomainEvent):
    order_id: str = ""
    venue: str = ""


@dataclass(frozen=True, slots=True)
class OrderFilled(DomainEvent):
    order_id: str = ""
    fill_id: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class PositionUpdated(DomainEvent):
    instrument_id: str = ""
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class TradeIntentCreated(DomainEvent):
    intent_id: str = ""
    instrument_id: str = ""
    side: str = ""
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskDecisionRecorded(DomainEvent):
    intent_id: str = ""
    decision: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionRequestApproved(DomainEvent):
    order_id: str = ""
    broker_connection_id: str | None = None
    execution_mode: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionReceiptRecorded(DomainEvent):
    order_id: str = ""
    receipt_id: str = ""
    outcome: str = ""


@dataclass(frozen=True, slots=True)
class FillRecorded(DomainEvent):
    order_id: str = ""
    fill_id: str = ""
    instrument_id: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class GenericDomainEvent(DomainEvent):
    """Extensible event for non-critical facts during early development."""

    event_type: str = ""
    data: Mapping[str, Any] | None = None
