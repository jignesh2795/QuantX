"""Canonical broker/local order reconciliation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from quantx.execution.order_lifecycle import OrderLifecycleStatus


class OrderReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISSING_BROKER_ORDER = "MISSING_BROKER_ORDER"
    MISSING_LOCAL_ORDER = "MISSING_LOCAL_ORDER"
    STATE_MISMATCH = "STATE_MISMATCH"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OrderObservation:
    order_id: UUID
    status: OrderLifecycleStatus
    requested_quantity: str
    filled_quantity: str
    broker_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderReconciliationResult:
    order_id: UUID
    status: OrderReconciliationStatus
    message: str


class OrderReconciler:
    """Compare locally recorded order state with an explicit broker snapshot."""

    def reconcile(
        self,
        *,
        local: OrderObservation | None,
        broker: OrderObservation | None,
    ) -> OrderReconciliationResult:
        if local is None and broker is not None:
            return OrderReconciliationResult(
                broker.order_id,
                OrderReconciliationStatus.MISSING_LOCAL_ORDER,
                "broker order has no matching local order",
            )
        if broker is None and local is not None:
            return OrderReconciliationResult(
                local.order_id,
                OrderReconciliationStatus.MISSING_BROKER_ORDER,
                "local order has no broker observation",
            )
        if local is None or broker is None:
            raise ValueError("at least one order observation is required")
        if local.order_id != broker.order_id:
            raise ValueError("order identity mismatch")
        if local.status != broker.status:
            return OrderReconciliationResult(
                local.order_id,
                OrderReconciliationStatus.STATE_MISMATCH,
                f"local={local.status}, broker={broker.status}",
            )
        if local.filled_quantity != broker.filled_quantity:
            return OrderReconciliationResult(
                local.order_id,
                OrderReconciliationStatus.QUANTITY_MISMATCH,
                f"local filled={local.filled_quantity}, broker filled={broker.filled_quantity}",
            )
        return OrderReconciliationResult(
            local.order_id,
            OrderReconciliationStatus.MATCHED,
            "order state matches",
        )
