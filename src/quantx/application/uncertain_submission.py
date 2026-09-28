"""Canonical recovery of receipts after an uncertain submission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.reconciliation.orders import OrderObservation


@dataclass(frozen=True, slots=True)
class UncertainSubmissionReceiptRecovery:
    """Reconstruct a receipt only from definitive broker-order evidence.

    This boundary deliberately does not infer fills, prices, or broker state.
    Filled and partially-filled observations therefore require real Fill
    evidence from the broker adapter.
    """

    def recover(
        self,
        request: ApprovedExecutionRequest,
        broker_order: OrderObservation,
        *,
        request_id: UUID,
        recovered_at: datetime,
        fills: tuple[Fill, ...] = (),
        source: str = "reconciliation",
        message: str = "",
    ) -> ExecutionReceipt | None:
        order = request.order
        if broker_order.order_id != order.client_order_id:
            raise ValueError("broker order identity does not match canonical order")
        if Decimal(broker_order.requested_quantity) != order.quantity:
            raise ValueError("broker requested quantity does not match canonical order")

        outcome, order_status = self._map_status(broker_order.status)
        if outcome is None or order_status is None:
            return None

        filled_quantity = sum((fill.quantity for fill in fills), Decimal("0"))
        if filled_quantity != Decimal(broker_order.filled_quantity):
            if fills or broker_order.status in {
                OrderLifecycleStatus.FILLED,
                OrderLifecycleStatus.PARTIALLY_FILLED,
            }:
                raise ValueError("fill quantity does not match broker order evidence")

        return ExecutionReceipt.from_order(
            order,
            request_id=request_id,
            outcome=outcome,
            order_status=order_status,
            executed_at=recovered_at,
            fills=fills,
            source=source,
            message=message,
            broker_order_id=broker_order.broker_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
            correlation_id=request.correlation_id,
        )

    @staticmethod
    def _map_status(
        status: OrderLifecycleStatus,
    ) -> tuple[ExecutionOutcome | None, OrderStatus | None]:
        mapping = {
            OrderLifecycleStatus.ACKNOWLEDGED: (
                ExecutionOutcome.ACCEPTED,
                OrderStatus.ACCEPTED,
            ),
            OrderLifecycleStatus.PARTIALLY_FILLED: (
                ExecutionOutcome.PARTIALLY_FILLED,
                OrderStatus.PARTIALLY_FILLED,
            ),
            OrderLifecycleStatus.FILLED: (
                ExecutionOutcome.FILLED,
                OrderStatus.FILLED,
            ),
            OrderLifecycleStatus.CANCELLED: (
                ExecutionOutcome.CANCELLED,
                OrderStatus.CANCELLED,
            ),
            OrderLifecycleStatus.REJECTED: (
                ExecutionOutcome.REJECTED,
                OrderStatus.REJECTED,
            ),
        }
        return mapping.get(status, (None, None))
