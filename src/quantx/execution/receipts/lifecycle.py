"""Order-level execution lifecycle state derived from immutable receipts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderStatus

from .models import ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ExecutionLifecycle:
    client_order_id: UUID | str
    order_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.CREATED

    def __post_init__(self) -> None:
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity must be within order quantity")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.order_quantity - self.filled_quantity

    @property
    def can_continue(self) -> bool:
        """Whether another separately approved execution may target the remainder."""
        return self.remaining_quantity > 0 and self.status is OrderStatus.PARTIALLY_FILLED

    def continuation_quantity(self, requested_quantity: Decimal | None = None) -> Decimal:
        """Return a safe continuation quantity without creating a new order.

        A continuation must be a new, separately approved execution request.
        This method only constrains its quantity to the currently evidenced
        remainder; it never reuses the original client-order identity.
        """
        if not self.can_continue:
            raise ValueError("execution lifecycle has no remaining partially-filled quantity")
        if requested_quantity is None:
            return self.remaining_quantity
        if requested_quantity <= 0:
            raise ValueError("continuation quantity must be positive")
        if requested_quantity > self.remaining_quantity:
            raise ValueError("continuation quantity exceeds remaining order quantity")
        return requested_quantity

    @property
    def is_complete(self) -> bool:
        return self.remaining_quantity == 0 or self.status in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
            OrderStatus.UNKNOWN,
        }

    def apply(self, receipt: ExecutionReceipt) -> "ExecutionLifecycle":
        if receipt.client_order_id != self.client_order_id:
            raise ValueError("receipt client_order_id does not match lifecycle")
        new_filled = self.filled_quantity + receipt.filled_quantity
        if new_filled > self.order_quantity:
            raise ValueError("cumulative fills exceed order quantity")
        return ExecutionLifecycle(
            client_order_id=self.client_order_id,
            order_quantity=self.order_quantity,
            filled_quantity=new_filled,
            status=receipt.order_status,
        )
