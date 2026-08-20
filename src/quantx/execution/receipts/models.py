"""Execution receipt records with explicit uncertainty semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ReceiptState(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionReceiptRecord:
    """Immutable receipt suitable for audit/reconciliation persistence."""

    receipt_id: UUID
    client_order_id: UUID
    state: ReceiptState
    observed_at: datetime
    external_order_id: str | None = None
    message: str = ""
    source: str = ""
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("source must not be empty")
