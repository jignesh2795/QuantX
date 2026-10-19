"""Boundary between risk-approved intent and broker execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .deployment import ExecutionContext, ExecutionMode
from .enums import PositionEffect
from .order_intents import TradeIntent
from .orders import Order
from .policy import PolicyResult
from .position_effect import PositionEvidence, resolve_position_effect
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
    position_evidence_cut: datetime | None = None
    position_evidence: PositionEvidence | None = None
    position_evidence_max_age: timedelta | None = None

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
        if self.product is not None:
            if not (self.execution_context.market_pack_id or "").strip():
                raise ValueError("an explicit product requires a market-pack id")
            if not (self.execution_context.rule_version or "").strip():
                raise ValueError("an explicit product requires a market-pack rule version")
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
        if self.effective_position_effect is not None:
            if self.effective_position_effect not in {
                PositionEffect.OPEN,
                PositionEffect.CLOSE,
            }:
                raise ValueError("resolved position effect must be OPEN or CLOSE")
            if self.position_effect not in {PositionEffect.AUTO, PositionEffect.CLOSE}:
                raise ValueError(
                    "an effective position effect is only valid for AUTO or CLOSE requests"
                )
            if self.position_effect is PositionEffect.CLOSE and (
                self.effective_position_effect is not PositionEffect.CLOSE
            ):
                raise ValueError("CLOSE position effect cannot resolve to OPEN")
        if self.position_effect is PositionEffect.AUTO:
            if self.effective_position_effect is None:
                raise ValueError(
                    "AUTO position effect requires a resolved effective effect (OPEN or CLOSE) "
                    "before approval"
                )
        if self.position_effect in {PositionEffect.CLOSE, PositionEffect.AUTO}:
            if self.position_evidence_cut is None:
                raise ValueError(
                    f"{self.position_effect.value} position effect requires the position "
                    "evidence cut used for approval"
                )
            if self.position_evidence is None:
                raise ValueError(
                    f"{self.position_effect.value} position effect requires the authoritative "
                    "position evidence used for approval"
                )
            if self.position_evidence_max_age is None:
                raise ValueError(
                    f"{self.position_effect.value} position effect requires a position "
                    "evidence freshness policy"
                )
            resolution = resolve_position_effect(
                self.order,
                evidence=self.position_evidence,
                max_evidence_age=self.position_evidence_max_age,
            )
            if resolution.evidence_cut != self.position_evidence_cut:
                raise ValueError("position evidence cut does not match the resolved evidence cut")
            if resolution.effective is not self.effective_position_effect:
                raise ValueError(
                    "effective position effect does not match the resolved position effect"
                )
        elif (
            self.position_evidence_cut is not None
            or self.position_evidence is not None
            or self.position_evidence_max_age is not None
        ):
            raise ValueError("position evidence is only valid for AUTO or CLOSE position effects")

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
    effective_position_effect: PositionEffect | None = None
    position_evidence_cut: datetime | None = None
    position_evidence: PositionEvidence | None = None
    position_evidence_max_age: timedelta | None = None

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
