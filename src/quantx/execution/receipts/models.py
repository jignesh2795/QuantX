"""Immutable execution receipts with explicit uncertainty and provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import AccountId, BrokerConnectionId


class ExecutionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    request_id: UUID
    client_order_id: UUID | str
    outcome: ExecutionOutcome
    order_status: OrderStatus
    executed_at: datetime
    fills: tuple[Fill, ...] = ()
    message: str = ""
    simulated: bool = False
    source: str = ""
    model_profile: str = ""
    model_version: str = ""
    assumptions: tuple[str, ...] = ()
    fee: Decimal = Decimal("0")
    broker_order_id: str | None = None
    raw_reference: str | None = None
    correlation_id: str | None = None
    receipt_id: UUID = field(default_factory=uuid4)
    order_id: UUID | None = None
    account_id: AccountId | None = None
    connection_id: BrokerConnectionId | None = None

    def __post_init__(self) -> None:
        if isinstance(self.client_order_id, str) and not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        if self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")
        if self.fee < 0:
            raise ValueError("fee cannot be negative")
        if any(fill.client_order_id != self.client_order_id for fill in self.fills):
            raise ValueError("all fills must belong to the receipt client_order_id")
        if self.outcome is ExecutionOutcome.FILLED and self.order_status is not OrderStatus.FILLED:
            raise ValueError("filled receipt must have FILLED order status")
        if self.outcome is ExecutionOutcome.PARTIALLY_FILLED and self.order_status is not OrderStatus.PARTIALLY_FILLED:
            raise ValueError("partial receipt must have PARTIALLY_FILLED order status")


# Backward-compatible names used by early execution consumers.
ExecutionReceiptRecord = ExecutionReceipt
ReceiptState = ExecutionOutcome
ReceiptOutcome = ExecutionOutcome
