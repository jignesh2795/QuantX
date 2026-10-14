"""Bridge paper-venue results into QuantX order lifecycle and accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill, Order
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.order_lifecycle import (
    OrderLifecycle,
    OrderLifecycleEvent,
    OutcomeConfidence,
)

from .broker import PaperBroker
from .evidence import SimulationEvidenceStatus
from .fills import MarketSnapshot
from .order_types import PaperOrderSpec, PaperOrderType, PaperTimeInForce
from .profile import OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class PaperExecutionOutcome:
    lifecycle_status: OrderStatus
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
        lifecycle.apply(
            OrderLifecycleEvent(
                order_id=order.client_order_id,
                status=OrderStatus.SUBMITTED,
                observed_at=observed_at,
                source="paper",
            )
        )

        paper_type = PaperOrderType(order.order_type.value)
        # Unsupported time-in-force values (FOK, GTC, ...) are rejected
        # here rather than silently modeled as DAY or IOC.
        time_in_force = PaperTimeInForce(order.time_in_force.value)
        spec = PaperOrderSpec(
            side=order.side.value,
            order_type=paper_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            time_in_force=time_in_force,
        )
        result = self.broker.execute(
            spec,
            snapshot=snapshot,
            submitted_at_ns=submitted_at_ns,
            order_book=order_book,
        )

        if result.evidence.status is SimulationEvidenceStatus.INSUFFICIENT:
            lifecycle.apply(
                OrderLifecycleEvent(
                    order_id=order.client_order_id,
                    status=OrderStatus.UNKNOWN,
                    observed_at=observed_at,
                    source="paper",
                    message=result.evidence.reason,
                    confidence=OutcomeConfidence.UNCERTAIN,
                )
            )
            return PaperExecutionOutcome(lifecycle.status, None, None, result.evidence.reason)

        if result.fill is None or result.fill.quantity <= 0:
            if time_in_force is PaperTimeInForce.IOC:
                # The immediate attempt is modeled and confirmed, but nothing
                # executed: the unfilled quantity is cancelled, not rested.
                self._cancel_remainder(lifecycle, order, Decimal("0"), observed_at)
                return PaperExecutionOutcome(
                    lifecycle.status, None, None, "ioc attempt executed nothing; cancelled"
                )
            return PaperExecutionOutcome(lifecycle.status, None, None, result.match.reason)

        if result.fill_at_ns is None:
            raise ValueError("fill_at_ns is required when a paper fill is present")

        filled_at = datetime.fromtimestamp(result.fill_at_ns / 1_000_000_000, tz=UTC)
        fill = Fill(
            client_order_id=order.client_order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=result.fill.quantity,
            price=result.fill.price,
            filled_at=filled_at,
        )
        status = OrderStatus.PARTIALLY_FILLED if result.fill.partial else OrderStatus.FILLED
        lifecycle.apply(
            OrderLifecycleEvent(
                order_id=order.client_order_id,
                status=status,
                observed_at=filled_at,
                source="paper",
                order_quantity=order.quantity,
                filled_quantity=result.fill.quantity,
            )
        )
        ledger = self.accounting.apply(fill, fee=result.fill.fee)
        if time_in_force is PaperTimeInForce.IOC and result.fill.partial:
            # Only the evidenced partial fill stands; the modeled remainder
            # was not executed and is cancelled rather than rested.
            self._cancel_remainder(lifecycle, order, result.fill.quantity, filled_at)
            return PaperExecutionOutcome(
                lifecycle.status, ledger, fill, "ioc partial fill; remainder cancelled"
            )
        return PaperExecutionOutcome(lifecycle.status, ledger, fill, "paper fill applied")

    @staticmethod
    def _cancel_remainder(
        lifecycle: OrderLifecycle,
        order: Order,
        filled_quantity: Decimal,
        observed_at: datetime,
    ) -> None:
        """Record an IOC remainder cancellation against evidenced fills only."""
        lifecycle.apply(
            OrderLifecycleEvent(
                order_id=order.client_order_id,
                status=OrderStatus.CANCELLED,
                observed_at=observed_at,
                source="paper",
                order_quantity=order.quantity,
                filled_quantity=filled_quantity,
            )
        )
