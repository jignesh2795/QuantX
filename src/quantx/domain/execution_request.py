"""Boundary between risk-approved intent and broker execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .deployment import ExecutionContext, ExecutionMode
from .enums import PositionEffect
from .order_intents import TradeIntent
from .orders import Order
from .policy import PolicyResult
from .risk import RiskDecision, RiskResult
from .value_objects import ProductCode


@dataclass(frozen=True, slots=True)
class ApprovedExecutionRequest:
    order: Order
    execution_context: ExecutionContext
    risk_result: RiskResult
    policy_result: PolicyResult | None = None
    required_margin: Decimal = Decimal("0")
    parent_client_order_id: str | None = None
    product: ProductCode | None = None
    position_effect: PositionEffect | None = None
    effective_position_effect: PositionEffect | None = None

    def __post_init__(self) -> None:
        if self.required_margin < 0:
            raise ValueError("required_margin cannot be negative")
        if self.risk_result.decision is not RiskDecision.APPROVE:
            raise ValueError("execution request requires an approved risk result")
        if self.execution_context.execution_mode is ExecutionMode.LIVE:
            if self.execution_context.broker_connection_id is None:
                raise ValueError("live execution requires a broker connection")
            if self.policy_result is None or not self.policy_result.approved:
                raise ValueError("live execution requires an approved execution policy")
        if self.product is not None and not str(self.product).strip():
            raise ValueError("approved request product must be non-empty when specified")
        if self.order.product is not None:
            if self.product is None:
                raise ValueError(
                    "approved request must identify the resolved product when the order "
                    "specifies one"
                )
            if self.product != self.order.product:
                raise ValueError("approved request product does not match the order product")
        if self.position_effect is not None and self.position_effect not in {
            PositionEffect.OPEN,
            PositionEffect.CLOSE,
            PositionEffect.AUTO,
        }:
            raise ValueError("position_effect must be OPEN, CLOSE, AUTO, or None")
        if self.order.position_effect is not None:
            if self.position_effect is None:
                raise ValueError(
                    "approved request must carry the requested position effect from the order"
                )
            if self.position_effect is not self.order.position_effect:
                raise ValueError(
                    "approved request position effect does not match the order position effect"
                )
        if self.position_effect == PositionEffect.AUTO:
            if self.effective_position_effect is None:
                raise ValueError(
                    "AUTO position effect requires a resolved effective effect (OPEN or CLOSE) "
                    "before approval"
                )
            if self.effective_position_effect not in {PositionEffect.OPEN, PositionEffect.CLOSE}:
                raise ValueError("resolved AUTO effect must be OPEN or CLOSE")

    @property
    def correlation_id(self) -> str:
        return self.parent_client_order_id or str(self.order.client_order_id)


@dataclass(frozen=True, slots=True)
class PendingExecutionRecoveryRequest:
    """Minimal request projection required to reconstruct broker evidence."""

    order: Order
    execution_context: ExecutionContext
    parent_client_order_id: str | None = None
    product: ProductCode | None = None
    position_effect: PositionEffect | None = None

    @property
    def correlation_id(self) -> str:
        return self.parent_client_order_id or str(self.order.client_order_id)


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
        required_capabilities=intent.required_capabilities,
        product=intent.product,
        position_effect=intent.position_effect,
    )
