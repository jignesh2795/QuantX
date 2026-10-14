"""Canonical order-status reduction and compatibility lifecycle adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quantx.domain.enums import OrderStatus


class OrderLifecycleStatus(StrEnum):
    """Deprecated input compatibility shim; new code must use OrderStatus.

    ACKNOWLEDGED is normalized to OrderStatus.ACCEPTED at OrderLifecycleEvent's
    boundary. This enum is retained only while external callers migrate.
    """

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


TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
AUTHORITATIVE_RESOLUTION_STATUSES = frozenset(
    {
        OrderStatus.SUBMITTED,
        OrderStatus.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    }
)
CONTRADICTORY_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
        OrderStatus.CANCEL_PENDING,
    }
)

_ORDER_STATUS_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED, OrderStatus.FAILED}
    ),
    OrderStatus.PENDING_SUBMIT: frozenset(
        {
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.ACCEPTED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.CANCEL_PENDING: frozenset(
        {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.UNKNOWN: frozenset(),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.FAILED: frozenset(),
}


def _canonical_status(status: OrderStatus | OrderLifecycleStatus) -> OrderStatus:
    """Normalize the sole legacy synonym at the compatibility boundary."""
    if isinstance(status, OrderStatus):
        return status
    if status is OrderLifecycleStatus.ACKNOWLEDGED:
        return OrderStatus.ACCEPTED
    return OrderStatus(status.value)


@dataclass(frozen=True, slots=True)
class OrderStatusReduction:
    """Evidence-preserving result from the shared order-status reducer."""

    status: OrderStatus
    requires_reconciliation: bool
    anomalies: tuple[str, ...] = ()


def is_terminal_order_status(status: OrderStatus) -> bool:
    return status in TERMINAL_ORDER_STATUSES


def _is_reachable_status(current_status: OrderStatus, observed_status: OrderStatus) -> bool:
    """Return whether the target can follow the current state without moving backwards."""
    visited: set[OrderStatus] = set()
    pending = list(_ORDER_STATUS_TRANSITIONS[current_status])
    while pending:
        candidate = pending.pop()
        if candidate is observed_status:
            return True
        if candidate not in visited:
            visited.add(candidate)
            pending.extend(_ORDER_STATUS_TRANSITIONS[candidate] - visited)
    return False


def _reduce_order_status(
    current_status: OrderStatus,
    observed_status: OrderStatus,
    *,
    current_filled: Decimal = Decimal("0"),
    added_fill: Decimal = Decimal("0"),
    order_quantity: Decimal | None = None,
    requires_reconciliation: bool = False,
    anomalies: tuple[str, ...] = (),
    reconciliation_authorized: bool = False,
    cancel_acknowledged: bool = False,
    strict_transition: bool = False,
) -> OrderStatusReduction:
    """Reduce one normalized status observation using shared lifecycle rules.

    Receipt reconstruction supplies quantity/fill evidence and may be invoked
    only through the explicit reconciliation entrypoint for authority. The
    lightweight event adapter uses strict transition checking but has no fill
    accounting of its own.
    """
    anomaly_list = list(anomalies)

    def flag_anomaly(message: str) -> None:
        if message not in anomaly_list:
            anomaly_list.append(message)

    new_filled = current_filled + added_fill
    if order_quantity is not None:
        if order_quantity <= 0 or current_filled < 0 or added_fill < 0:
            raise ValueError("order quantities must be non-negative with a positive order quantity")
        if new_filled > order_quantity:
            raise ValueError("cumulative fills exceed order quantity")

    def result(status: OrderStatus, *, needs_reconciliation: bool) -> OrderStatusReduction:
        return OrderStatusReduction(
            status=status,
            requires_reconciliation=needs_reconciliation,
            anomalies=tuple(anomaly_list),
        )

    # Terminal states are absorbing for ordinary observations. Conflicting
    # later statuses and late fills remain evidence, not replacements.
    if is_terminal_order_status(current_status):
        if observed_status is not current_status:
            flag_anomaly(
                f"conflicting status {observed_status.value} observed after terminal "
                f"status {current_status.value}"
            )
            requires_reconciliation = True
        if added_fill > 0 and current_status is not OrderStatus.FILLED:
            flag_anomaly(
                f"late fill evidence observed after terminal status {current_status.value}"
            )
            requires_reconciliation = True
        if (
            order_quantity is not None
            and new_filled == order_quantity
            and current_status is not OrderStatus.FILLED
        ):
            flag_anomaly(
                f"terminal status {current_status.value} conflicts with "
                "full-quantity fill evidence"
            )
            requires_reconciliation = True
        elif (
            reconciliation_authorized
            and observed_status is current_status
            and added_fill == 0
            and (order_quantity is None or new_filled < order_quantity)
        ):
            requires_reconciliation = False
        return result(current_status, needs_reconciliation=requires_reconciliation)

    if current_status is OrderStatus.UNKNOWN:
        if cancel_acknowledged and observed_status is OrderStatus.CANCEL_PENDING:
            flag_anomaly("cancel acknowledgement does not resolve prior UNKNOWN order state")
            return result(OrderStatus.CANCEL_PENDING, needs_reconciliation=True)
        if (
            not reconciliation_authorized
            or observed_status not in AUTHORITATIVE_RESOLUTION_STATUSES
        ):
            if observed_status is not OrderStatus.UNKNOWN:
                flag_anomaly(
                    f"status {observed_status.value} cannot resolve UNKNOWN without "
                    "authoritative reconciliation"
                )
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        requires_reconciliation = False
        if order_quantity is not None and new_filled == order_quantity:
            if observed_status in CONTRADICTORY_TERMINAL_STATUSES:
                flag_anomaly(
                    f"status {observed_status.value} conflicts with full-quantity fill evidence"
                )
                requires_reconciliation = True
            return result(OrderStatus.FILLED, needs_reconciliation=requires_reconciliation)

        if order_quantity is not None and observed_status is OrderStatus.FILLED:
            flag_anomaly("FILLED status lacks full-quantity fill evidence")
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        if (
            order_quantity is not None
            and observed_status is OrderStatus.ACCEPTED
            and new_filled > 0
        ):
            flag_anomaly("ACCEPTED status conflicts with existing fill evidence")
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        if (
            order_quantity is not None
            and observed_status is OrderStatus.PARTIALLY_FILLED
            and new_filled == 0
        ):
            flag_anomaly("PARTIALLY_FILLED status has no fill evidence")
            return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

        if (
            order_quantity is not None
            and new_filled > 0
            and observed_status not in TERMINAL_ORDER_STATUSES
        ):
            return result(
                OrderStatus.PARTIALLY_FILLED,
                needs_reconciliation=requires_reconciliation,
            )
        return result(observed_status, needs_reconciliation=requires_reconciliation)

    if observed_status is OrderStatus.UNKNOWN:
        return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

    if strict_transition and observed_status not in _ORDER_STATUS_TRANSITIONS[current_status]:
        if not reconciliation_authorized or not _is_reachable_status(
            current_status, observed_status
        ):
            raise ValueError(f"invalid order transition: {current_status} -> {observed_status}")

    if order_quantity is not None and new_filled == order_quantity:
        if observed_status in CONTRADICTORY_TERMINAL_STATUSES:
            flag_anomaly(
                f"status {observed_status.value} conflicts with full-quantity fill evidence"
            )
            requires_reconciliation = True
        elif reconciliation_authorized and observed_status in AUTHORITATIVE_RESOLUTION_STATUSES:
            requires_reconciliation = False
        return result(OrderStatus.FILLED, needs_reconciliation=requires_reconciliation)

    if order_quantity is not None and observed_status is OrderStatus.FILLED:
        flag_anomaly("FILLED status lacks full-quantity fill evidence")
        return result(OrderStatus.UNKNOWN, needs_reconciliation=True)

    if reconciliation_authorized and observed_status in AUTHORITATIVE_RESOLUTION_STATUSES:
        requires_reconciliation = False

    if is_terminal_order_status(observed_status):
        return result(observed_status, needs_reconciliation=requires_reconciliation)

    if observed_status is OrderStatus.CANCEL_PENDING:
        return result(
            OrderStatus.CANCEL_PENDING,
            needs_reconciliation=requires_reconciliation,
        )

    if order_quantity is not None and new_filled > 0:
        return result(
            OrderStatus.PARTIALLY_FILLED,
            needs_reconciliation=requires_reconciliation,
        )

    return result(observed_status, needs_reconciliation=requires_reconciliation)


@dataclass(frozen=True, slots=True)
class OrderLifecycleEvent:
    order_id: UUID
    status: OrderStatus | OrderLifecycleStatus
    observed_at: datetime
    source: str
    broker_order_id: str | None = None
    message: str = ""
    confidence: OutcomeConfidence = OutcomeConfidence.CONFIRMED
    order_quantity: Decimal | None = None
    filled_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        canonical_status = _canonical_status(self.status)
        object.__setattr__(self, "status", canonical_status)
        if (self.order_quantity is None) != (self.filled_quantity is None):
            raise ValueError("order and filled quantities must be supplied together")
        if self.order_quantity is None:
            if canonical_status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
                raise ValueError("filled statuses require quantity-backed evidence")
            return
        if not isinstance(self.order_quantity, Decimal) or not self.order_quantity.is_finite():
            raise ValueError("order quantity must be a finite Decimal")
        if not isinstance(self.filled_quantity, Decimal) or not self.filled_quantity.is_finite():
            raise ValueError("filled quantity must be a finite Decimal")
        if self.order_quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled quantity must be within order quantity")
        if canonical_status is OrderStatus.FILLED and self.filled_quantity != self.order_quantity:
            raise ValueError("FILLED status requires full-quantity evidence")
        if canonical_status is OrderStatus.PARTIALLY_FILLED and not (
            Decimal("0") < self.filled_quantity < self.order_quantity
        ):
            raise ValueError("PARTIALLY_FILLED status requires partial-quantity evidence")


class OrderLifecycle:
    """Compatibility event facade using the canonical status reducer."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        self.status = OrderStatus.CREATED
        self.order_quantity: Decimal | None = None
        self.filled_quantity = Decimal("0")
        self.requires_reconciliation = False
        self.anomalies: tuple[str, ...] = ()

    def apply(self, event: OrderLifecycleEvent) -> None:
        self._apply(
            event,
            reconciliation_authorized=False,
            cancel_acknowledged=False,
        )

    def reconcile(self, event: OrderLifecycleEvent) -> None:
        """Apply a validated observation from the authoritative reconciliation path."""
        self._apply(
            event,
            reconciliation_authorized=True,
            cancel_acknowledged=False,
        )

    def acknowledge_cancel(self, event: OrderLifecycleEvent) -> None:
        """Record an acknowledged cancel operation without resolving UNKNOWN."""
        if event.status is not OrderStatus.CANCEL_PENDING:
            raise ValueError("cancel acknowledgement must have CANCEL_PENDING status")
        self._apply(
            event,
            reconciliation_authorized=False,
            cancel_acknowledged=True,
        )

    def _apply(
        self,
        event: OrderLifecycleEvent,
        *,
        reconciliation_authorized: bool,
        cancel_acknowledged: bool,
    ) -> None:
        if event.order_id != self.order_id:
            raise ValueError("event order_id does not match lifecycle")
        observed_order_quantity = event.order_quantity or self.order_quantity
        added_fill = Decimal("0")
        if event.order_quantity is not None:
            if (
                self.order_quantity is not None
                and event.order_quantity != self.order_quantity
            ):
                raise ValueError("order quantity changed during lifecycle")
            assert event.filled_quantity is not None
            if event.filled_quantity < self.filled_quantity:
                raise ValueError("observed cumulative filled quantity cannot decrease")
            added_fill = event.filled_quantity - self.filled_quantity

        reduction = _reduce_order_status(
            self.status,
            _canonical_status(event.status),
            current_filled=self.filled_quantity,
            added_fill=added_fill,
            order_quantity=observed_order_quantity,
            requires_reconciliation=self.requires_reconciliation,
            anomalies=self.anomalies,
            reconciliation_authorized=reconciliation_authorized,
            cancel_acknowledged=cancel_acknowledged,
            strict_transition=True,
        )
        self.status = reduction.status
        self.order_quantity = observed_order_quantity
        self.filled_quantity += added_fill
        self.requires_reconciliation = reduction.requires_reconciliation
        self.anomalies = reduction.anomalies


__all__ = [
    "OrderLifecycle",
    "OrderLifecycleEvent",
    "OrderLifecycleStatus",
    "OrderStatusReduction",
    "OutcomeConfidence",
    "TERMINAL_ORDER_STATUSES",
    "AUTHORITATIVE_RESOLUTION_STATUSES",
    "CONTRADICTORY_TERMINAL_STATUSES",
    "is_terminal_order_status",
]
