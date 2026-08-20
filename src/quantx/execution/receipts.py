"""Immutable execution receipts that preserve broker outcomes and provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class ReceiptOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    order_id: UUID
    account_id: UUID
    connection_id: UUID
    client_order_id: str
    broker_order_id: str | None
    outcome: ReceiptOutcome
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    fee: Decimal
    observed_at: datetime
    source: str
    raw_reference: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        if self.filled_quantity < 0:
            raise ValueError("filled_quantity cannot be negative")
        if self.average_fill_price is not None and self.average_fill_price < 0:
            raise ValueError("average_fill_price cannot be negative")
        if self.fee < 0:
            raise ValueError("fee cannot be negative")
        if not self.source.strip():
            raise ValueError("source must not be empty")
