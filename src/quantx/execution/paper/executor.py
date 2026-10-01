"""Bridge paper-venue results into QuantX order lifecycle and accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill, Order
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.order_lifecycle import (
    OrderLifecycle,
    OrderLifecycleEvent,
    OrderLifecycleStatus,
)

from .broker import PaperBroker
from .evidence import SimulationEvidenceStatus
from .fills import MarketSnapshot
from .order_types import PaperOrderSpec, PaperOrderType
from .profile import OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class PaperExecutionOutcome:
    lifecycle_status: OrderLifecycleStatus
    ledger_entry: PositionLedgerEntry | None
    fill: Fill | None
    reason: str


class PaperOrderExecutor:
    """Execute an existing QuantX order without creating a second order model."""

    def __init__(self, broker: PaperBroker, accounting: FillAccounting) -> None:
        self.broker = broker
        self.accounting = accounting

    def execute(
        self,
        order: Order,
        *,
        snapshot: MarketSnapshot | None,
        submitted_at_ns: int,
        observed_at: datetime,
        order_book: OrderBookSnapshot | None = None,
    ) -> PaperExecutionOutcome:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        lifecycle = OrderLifecycle(order.client_order_id)
        lifecycle.apply(OrderLifecycleEvent(
            order_id=order.client_order_id,
            status=OrderLifecycleStatus.SUBMITTED,
            observed_at=observed_at,
            source="paper",
        ))

        paper_type = PaperOrderType(order.order_type.value)
        spec = PaperOrderSpec(
            side=order.side.value,
            order_type=paper_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
        )
        result = self.broker.execute(
            spec,
            snapshot=snapshot,
            submitted_at_ns=submitted_at_ns,
            order_book=order_book,
        )

        if result.evidence.status is SimulationEvidenceStatus.INSUFFICIENT:
            lifecycle.apply(OrderLifecycleEvent(
                order_id=order.client_order_id,
                status=OrderLifecycleStatus.UNKNOWN,
                observed_at=observed_at,
                source="paper",
                message=result.evidence.reason,
                confidence="UNCERTAIN",
            ))
            return PaperExecutionOutcome(lifecycle.status, None, None, result.evidence.reason)

        if result.fill is None or result.fill.quantity <= 0:
            return PaperExecutionOutcome(lifecycle.status, None, None, result.match.reason)

        filled_at = datetime.fromtimestamp(result.fill_at_ns / 1_000_000_000, tz=timezone.utc)
        fill = Fill(
            client_order_id=order.client_order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=result.fill.quantity,
            price=result.fill.price,
            filled_at=filled_at,
        )
        status = (
            OrderLifecycleStatus.PARTIALLY_FILLED
            if result.fill.partial
            else OrderLifecycleStatus.FILLED
        )
        lifecycle.apply(OrderLifecycleEvent(
            order_id=order.client_order_id,
            status=status,
            observed_at=filled_at,
            source="paper",
        ))
        ledger = self.accounting.apply(fill, fee=result.fill.fee)
        return PaperExecutionOutcome(lifecycle.status, ledger, fill, "paper fill applied")
