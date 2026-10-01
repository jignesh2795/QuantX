"""Explicit order lifecycle and uncertain-outcome semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class OrderLifecycleStatus(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class OutcomeConfidence(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class OrderLifecycleEvent:
    order_id: UUID
    status: OrderLifecycleStatus
    observed_at: datetime
    source: str
    broker_order_id: str | None = None
    message: str = ""
    confidence: OutcomeConfidence = OutcomeConfidence.CONFIRMED

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("source must not be empty")


class OrderLifecycle:
    """Small deterministic state machine; UNKNOWN is terminal until reconciled."""

    _allowed: dict[OrderLifecycleStatus, frozenset[OrderLifecycleStatus]] = {
        OrderLifecycleStatus.CREATED: frozenset({OrderLifecycleStatus.SUBMITTED}),
        OrderLifecycleStatus.SUBMITTED: frozenset({
            OrderLifecycleStatus.ACKNOWLEDGED,
            OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.REJECTED,
            OrderLifecycleStatus.UNKNOWN,
        }),
        OrderLifecycleStatus.ACKNOWLEDGED: frozenset({
            OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.CANCEL_PENDING,
            OrderLifecycleStatus.REJECTED,
            OrderLifecycleStatus.UNKNOWN,
        }),
        OrderLifecycleStatus.PARTIALLY_FILLED: frozenset({
            OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.CANCEL_PENDING,
            OrderLifecycleStatus.UNKNOWN,
        }),
        OrderLifecycleStatus.CANCEL_PENDING: frozenset({
            OrderLifecycleStatus.CANCELLED,
            OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.UNKNOWN,
        }),
        OrderLifecycleStatus.UNKNOWN: frozenset({
            OrderLifecycleStatus.ACKNOWLEDGED,
            OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.CANCELLED,
            OrderLifecycleStatus.REJECTED,
        }),
        OrderLifecycleStatus.FILLED: frozenset(),
        OrderLifecycleStatus.CANCELLED: frozenset(),
        OrderLifecycleStatus.REJECTED: frozenset(),
    }

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        self.status = OrderLifecycleStatus.CREATED

    def apply(self, event: OrderLifecycleEvent) -> None:
        if event.order_id != self.order_id:
            raise ValueError("event order_id does not match lifecycle")
        if event.status not in self._allowed[self.status]:
            raise ValueError(f"invalid order transition: {self.status} -> {event.status}")
        self.status = event.status
