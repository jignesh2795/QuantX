"""Order-level execution lifecycle state derived from immutable receipts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Order
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult

from .models import ExecutionReceipt


_TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
_AUTHORITATIVE_RESOLUTION_STATUSES = frozenset(
    {
        OrderStatus.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
_CONTRADICTORY_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
        OrderStatus.CANCEL_PENDING,
    }
)


@dataclass(frozen=True, slots=True)
class ExecutionLifecycle:
    client_order_id: UUID | str
    order_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.CREATED
    requires_reconciliation: bool = False
    anomalies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity must be within order quantity")
        if self.status is OrderStatus.UNKNOWN and not self.requires_reconciliation:
            object.__setattr__(self, "requires_reconciliation", True)
        if any(not anomaly.strip() for anomaly in self.anomalies):
            raise ValueError("lifecycle anomalies must be non-empty")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.order_quantity - self.filled_quantity

    @property
    def can_continue(self) -> bool:
        """Whether another separately approved execution may target the remainder.

        An anomaly or UNKNOWN state blocks progression even when partial fill
        evidence exists. A new child requires a clean, reconciled remainder.
        """
        return (
            not self.requires_reconciliation
            and self.remaining_quantity > 0
            and self.status is OrderStatus.PARTIALLY_FILLED
        )

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
        if risk_result.decision is not RiskDecision.APPROVE:
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
            intent_id=request.order.intent_id,
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
        """Whether this order has a resolved final state.

        UNKNOWN and any unresolved contradiction are not complete: they require
        authoritative reconciliation. A clean cancelled/rejected order may be
        complete while still having a positive, unfilled remainder.
        """
        if self.status is OrderStatus.UNKNOWN or self.requires_reconciliation:
            return False
        return self.remaining_quantity == 0 or self.status in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }

    @classmethod
    def rebuild(
        cls,
        client_order_id: UUID | str,
        order_quantity: Decimal,
        receipts: tuple[ExecutionReceipt, ...] | list[ExecutionReceipt],
        *,
        correlation_id: UUID | str | None = None,
        authoritative_reconciliation: bool = False,
    ) -> ExecutionLifecycle:
        """Reconstruct lifecycle state from authoritative immutable receipts.

        Receipt identity is the deduplication boundary. Replaying the same
        persisted receipt twice must never double-count its fill. Receipts
        are ordered deterministically by execution time and receipt ID.
        """
        unique: dict[UUID, ExecutionReceipt] = {}
        for receipt in receipts:
            existing = unique.get(receipt.receipt_id)
            if existing is not None:
                if existing != receipt:
                    raise ValueError("receipt ID maps to conflicting receipt data")
                continue
            unique[receipt.receipt_id] = receipt

        lifecycle = cls(client_order_id, order_quantity)
        ordered = sorted(
            unique.values(),
            key=lambda receipt: (receipt.executed_at, str(receipt.receipt_id)),
        )
        for receipt in ordered:
            lifecycle = lifecycle.apply(
                receipt,
                correlation_id=correlation_id,
                authoritative_reconciliation=authoritative_reconciliation,
            )
        return lifecycle

    def apply(
        self,
        receipt: ExecutionReceipt,
        *,
        correlation_id: UUID | str | None = None,
        authoritative_reconciliation: bool = False,
    ) -> ExecutionLifecycle:
        """Reduce one receipt without reopening terminal orders or hiding anomalies.

        Receipt fill evidence is retained even when its status conflicts with an
        already terminal lifecycle. UNKNOWN is unresolved by default; only a
        caller rebuilding authoritative reconciliation history may resolve it
        from a recognized broker status. Neither path automatically submits or
        continues an order.
        """
        accepted_correlation = (
            str(correlation_id) if correlation_id is not None else str(self.client_order_id)
        )
        if (
            receipt.client_order_id != self.client_order_id
            and receipt.correlation_id != accepted_correlation
        ):
            raise ValueError("receipt does not belong to lifecycle")

        new_filled = self.filled_quantity + receipt.filled_quantity
        if new_filled > self.order_quantity:
            raise ValueError("cumulative fills exceed order quantity")

        anomalies = list(self.anomalies)
        requires_reconciliation = self.requires_reconciliation
        current_status = self.status
        receipt_status = receipt.order_status

        def flag_anomaly(message: str) -> None:
            if message not in anomalies:
                anomalies.append(message)

        def result(status: OrderStatus, *, needs_reconciliation: bool) -> ExecutionLifecycle:
            return ExecutionLifecycle(
                client_order_id=self.client_order_id,
                order_quantity=self.order_quantity,
                filled_quantity=new_filled,
                status=status,
                requires_reconciliation=needs_reconciliation,
                anomalies=tuple(anomalies),
            )

        # Confirmed terminal states are absorbing. Later conflicting statuses
        # cannot rewrite them, but any new fill quantity is retained as evidence.
        if current_status in _TERMINAL_ORDER_STATUSES:
            if receipt_status is not current_status:
                flag_anomaly(
                    f"conflicting status {receipt_status.value} observed after terminal "
                    f"status {current_status.value}"
                )
                requires_reconciliation = True
            if receipt.filled_quantity > 0 and current_status is not OrderStatus.FILLED:
                flag_anomaly(
                    f"late fill evidence observed after terminal status {current_status.value}"
                )
                requires_reconciliation = True
            # A fresh authoritative observation confirming the same terminal
            # state can resolve a prior anomaly flag only when it adds no new fills.
            if (
                authoritative_reconciliation
                and receipt_status is current_status
                and receipt.filled_quantity == 0
            ):
                requires_reconciliation = False
            return result(current_status, needs_reconciliation=requires_reconciliation)

        # UNKNOWN is not a final outcome. Ordinary receipt application cannot
        # resolve it, even if a later event happens to carry a familiar status.
        if current_status is OrderStatus.UNKNOWN:
            if (
                not authoritative_reconciliation
                or receipt_status not in _AUTHORITATIVE_RESOLUTION_STATUSES
            ):
                if receipt_status is not OrderStatus.UNKNOWN:
                    flag_anomaly(
                        f"status {receipt_status.value} cannot resolve UNKNOWN without "
                        "authoritative reconciliation"
                    )
                return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

            requires_reconciliation = False
            if new_filled == self.order_quantity:
                if receipt_status in _CONTRADICTORY_TERMINAL_STATUSES:
                    flag_anomaly(
                        f"status {receipt_status.value} conflicts with full-quantity fill evidence"
                    )
                    requires_reconciliation = True
                return result(OrderStatus.FILLED, needs_reconciliation=requires_reconciliation)

            if receipt_status is OrderStatus.FILLED:
                flag_anomaly("FILLED status lacks full-quantity fill evidence")
                return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

            if receipt_status is OrderStatus.ACCEPTED and new_filled > 0:
                flag_anomaly("ACCEPTED status conflicts with existing fill evidence")
                return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

            if receipt_status is OrderStatus.PARTIALLY_FILLED and new_filled == 0:
                flag_anomaly("PARTIALLY_FILLED status has no fill evidence")
                return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

            if new_filled > 0 and receipt_status not in _TERMINAL_ORDER_STATUSES:
                return result(
                    OrderStatus.PARTIALLY_FILLED,
                    needs_reconciliation=requires_reconciliation,
                )
            return result(receipt_status, needs_reconciliation=requires_reconciliation)

        # From a known non-terminal state, fill quantity is the strongest signal
        # of completion. A contradictory terminal receipt is retained as an
        # anomaly instead of turning a fully filled order into CANCELLED/etc.
        if receipt_status is OrderStatus.UNKNOWN:
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        if new_filled == self.order_quantity:
            if receipt_status in _CONTRADICTORY_TERMINAL_STATUSES:
                flag_anomaly(
                    f"status {receipt_status.value} conflicts with full-quantity fill evidence"
                )
                requires_reconciliation = True
            elif (
                authoritative_reconciliation
                and receipt_status in _AUTHORITATIVE_RESOLUTION_STATUSES
            ):
                requires_reconciliation = False
            return result(OrderStatus.FILLED, needs_reconciliation=requires_reconciliation)

        if receipt_status is OrderStatus.FILLED:
            flag_anomaly("FILLED status lacks full-quantity fill evidence")
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        if (
            authoritative_reconciliation
            and receipt_status in _AUTHORITATIVE_RESOLUTION_STATUSES
        ):
            requires_reconciliation = False

        if receipt_status in _TERMINAL_ORDER_STATUSES:
            return result(receipt_status, needs_reconciliation=requires_reconciliation)

        if receipt_status is OrderStatus.CANCEL_PENDING:
            return result(
                OrderStatus.CANCEL_PENDING,
                needs_reconciliation=requires_reconciliation,
            )

        if new_filled > 0:
            return result(
                OrderStatus.PARTIALLY_FILLED,
                needs_reconciliation=requires_reconciliation,
            )

        return result(receipt_status, needs_reconciliation=requires_reconciliation)
