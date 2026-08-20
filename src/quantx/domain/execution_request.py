"""Boundary between risk-approved intent and broker execution.

An ApprovedExecutionRequest keeps execution identity alongside the normalized
Order. Broker adapters receive this envelope rather than a strategy-owned order.
"""

from __future__ import annotations

from dataclasses import dataclass

from .deployment import ExecutionContext
from .orders import Order
from .risk import RiskResult, RiskDecision


@dataclass(frozen=True, slots=True)
class ApprovedExecutionRequest:
    order: Order
    execution_context: ExecutionContext
    risk_result: RiskResult

    def __post_init__(self) -> None:
        if self.risk_result.decision is not RiskDecision.APPROVE:
            raise ValueError("execution request requires an approved risk result")

        if self.execution_context.execution_mode.value == "live" and self.execution_context.broker_connection_id is None:
            raise ValueError("live execution requires a broker connection")


def build_order_from_intent(intent) -> Order:
    """Create a normalized Order from a TradeIntent after risk approval.

    This helper intentionally does not perform risk checks. Callers must obtain
    an approved RiskResult first and construct ApprovedExecutionRequest.
    """
    return Order(
        instrument=intent.instrument,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        stop_price=intent.stop_price,
        time_in_force=intent.time_in_force,
    )
