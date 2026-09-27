"""Boundary between risk-approved intent and broker execution."""

from __future__ import annotations

from dataclasses import dataclass

from .deployment import ExecutionContext, ExecutionMode
from .order_intents import TradeIntent
from .orders import Order
from .policy import PolicyResult
from .risk import RiskDecision, RiskResult


@dataclass(frozen=True, slots=True)
class ApprovedExecutionRequest:
    order: Order
    execution_context: ExecutionContext
    risk_result: RiskResult
    policy_result: PolicyResult | None = None

    def __post_init__(self) -> None:
        if self.risk_result.decision is not RiskDecision.APPROVE:
            raise ValueError("execution request requires an approved risk result")
        if self.execution_context.execution_mode is ExecutionMode.LIVE:
            if self.execution_context.broker_connection_id is None:
                raise ValueError("live execution requires a broker connection")
            if self.policy_result is None or not self.policy_result.approved:
                raise ValueError("live execution requires an approved execution policy")

    @property
    def correlation_id(self) -> str:
        return str(self.order.client_order_id)


def build_order_from_intent(intent: TradeIntent) -> Order:
    return Order(
        instrument=intent.instrument,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        stop_price=intent.stop_price,
        time_in_force=intent.time_in_force,
        intent_id=intent.intent_id,
        strategy_id=intent.strategy_id,
        strategy_version=intent.strategy_version,
    )
