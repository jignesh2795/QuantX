"""Order-level execution lifecycle state derived from immutable receipts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Order
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskResult

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

    def continuation_client_order_id(self, requested_quantity: Decimal) -> UUID:
        """Derive a deterministic child identity for this continuation attempt."""
        quantity = self.continuation_quantity(requested_quantity)
        namespace = (
            self.client_order_id
            if isinstance(self.client_order_id, UUID)
            else uuid5(NAMESPACE_URL, str(self.client_order_id))
        )
        return uuid5(namespace, f"continuation:{self.filled_quantity}:{quantity}")

    def continuation_request(
        self,
        request: ApprovedExecutionRequest,
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        required_margin: Decimal = Decimal("0"),
        requested_quantity: Decimal | None = None,
    ) -> ApprovedExecutionRequest:
        """Build a separately approved request for only the evidenced remainder."""
        if request.order.client_order_id != self.client_order_id:
            raise ValueError("request client_order_id does not match lifecycle")
        quantity = self.continuation_quantity(requested_quantity)
        if risk_result.decision.value != "APPROVE":
            raise ValueError("continuation requires a fresh approved risk result")
        if required_margin < 0:
            raise ValueError("required_margin cannot be negative")
        child_order = Order(
            instrument=request.order.instrument,
            side=request.order.side,
            order_type=request.order.order_type,
            quantity=quantity,
            limit_price=request.order.limit_price,
            stop_price=request.order.stop_price,
            time_in_force=request.order.time_in_force,
            client_order_id=self.continuation_client_order_id(quantity),
            strategy_id=request.order.strategy_id,
            strategy_version=request.order.strategy_version,
            required_capabilities=request.order.required_capabilities,
        )
        return ApprovedExecutionRequest(
            order=child_order,
            execution_context=request.execution_context,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            parent_client_order_id=str(self.client_order_id),
        )

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
        if (
            receipt.client_order_id != self.client_order_id
            and receipt.correlation_id != str(self.client_order_id)
        ):
            raise ValueError("receipt does not belong to lifecycle")
        new_filled = self.filled_quantity + receipt.filled_quantity
        if new_filled > self.order_quantity:
            raise ValueError("cumulative fills exceed order quantity")
        return ExecutionLifecycle(
            client_order_id=self.client_order_id,
            order_quantity=self.order_quantity,
            filled_quantity=new_filled,
            status=receipt.order_status,
        )
