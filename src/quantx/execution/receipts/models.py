"""Immutable execution receipts with explicit uncertainty and provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill, Order
from quantx.domain.value_objects import AccountId, BrokerConnectionId


class ExecutionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"


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

    @classmethod
    def from_order(
        cls,
        order: Order,
        *,
        request_id: UUID,
        outcome: ExecutionOutcome,
        order_status: OrderStatus,
        executed_at: datetime,
        fills: tuple[Fill, ...] = (),
        message: str = "",
        simulated: bool = False,
        source: str = "",
        model_profile: str = "",
        model_version: str = "",
        assumptions: tuple[str, ...] = (),
        fee: Decimal = Decimal("0"),
        broker_order_id: str | None = None,
        raw_reference: str | None = None,
        correlation_id: str | None = None,
        receipt_id: UUID | None = None,
        account_id: AccountId | None = None,
        connection_id: BrokerConnectionId | None = None,
    ) -> ExecutionReceipt:
        """Construct a receipt while binding fill evidence to the canonical order."""
        cls._validate_fills_against_order(order, fills, outcome)
        return cls(
            request_id=request_id,
            client_order_id=order.client_order_id,
            outcome=outcome,
            order_status=order_status,
            executed_at=executed_at,
            fills=fills,
            message=message,
            simulated=simulated,
            source=source,
            model_profile=model_profile,
            model_version=model_version,
            assumptions=assumptions,
            fee=fee,
            broker_order_id=broker_order_id,
            raw_reference=raw_reference,
            correlation_id=correlation_id,
            receipt_id=receipt_id or uuid4(),
            order_id=order.client_order_id,
            account_id=account_id,
            connection_id=connection_id,
        )

    @staticmethod
    def _validate_fills_against_order(
        order: Order,
        fills: tuple[Fill, ...],
        outcome: ExecutionOutcome,
    ) -> None:
        execution_ids = [fill.execution_id for fill in fills]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("fills must have unique execution_id values")
        if any(fill.instrument != order.instrument for fill in fills):
            raise ValueError("all fills must match the order instrument")
        if any(fill.side is not order.side for fill in fills):
            raise ValueError("all fills must match the order side")
        total_filled = sum((fill.quantity for fill in fills), Decimal("0"))
        if total_filled > order.quantity:
            raise ValueError("fill quantity cannot exceed order quantity")
        if outcome is ExecutionOutcome.FILLED and total_filled != order.quantity:
            raise ValueError("filled receipt fills must equal order quantity")
        if outcome is ExecutionOutcome.PARTIALLY_FILLED and not (
            Decimal("0") < total_filled < order.quantity
        ):
            raise ValueError(
                "partially filled receipt fills must be between zero and order quantity"
            )

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
        if (
            self.outcome in {ExecutionOutcome.FILLED, ExecutionOutcome.PARTIALLY_FILLED}
            and not self.fills
        ):
            raise ValueError("filled receipt outcomes require at least one fill")
        if (
            self.outcome is ExecutionOutcome.PARTIALLY_FILLED
            and self.order_status is not OrderStatus.PARTIALLY_FILLED
        ):
            raise ValueError("partial receipt must have PARTIALLY_FILLED order status")


# Backward-compatible names used by early execution consumers.
ExecutionReceiptRecord = ExecutionReceipt
ReceiptState = ExecutionOutcome
ReceiptOutcome = ExecutionOutcome
