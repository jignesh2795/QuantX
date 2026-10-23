"""Boundary between risk-approved intent and broker execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from .deployment import ExecutionContext, ExecutionMode
from .enums import PositionEffect
from .instrument_registry import InstrumentResolution
from .order_intents import TradeIntent
from .orders import Order
from .policy import PolicyResult
from .position_effect import (
    AbsentPositionEffectResolution,
    PositionEvidence,
    resolve_position_effect,
)
from .product_selection import ProductSelectionResolution
from .risk import RiskDecision, RiskResult
from .value_objects import ProductCode


def validate_order_product_symmetry(
    order: Order,
    product: ProductCode | None,
    *,
    execution_context: ExecutionContext,
    product_resolution: ProductSelectionResolution | None = None,
) -> None:
    """Fail closed unless the request product mirrors the executed order.

    The order is the executed contract: a request may neither drop the
    resolved product the order carries nor claim a product the order does not
    carry. The only coherent states are both absent or both identical, and a
    resolved product always requires the market-pack and rule identity that
    selected it plus the validated proof that the policy supported it.
    """
    if product is None and product_resolution is not None:
        raise ValueError("an absent product cannot carry a product selection resolution")
    if product is not None:
        if not str(product).strip():
            raise ValueError("resolved product must be non-empty when specified")
        if not (execution_context.market_pack_id or "").strip():
            raise ValueError("a resolved product requires a market-pack id")
        if not (execution_context.rule_version or "").strip():
            raise ValueError("a resolved product requires a market-pack rule version")
    if order.product is not None:
        if product is None:
            raise ValueError("the resolved product must be identified when the order specifies one")
        if product != order.product:
            raise ValueError("resolved product does not match the order product")
    elif product is not None:
        raise ValueError("a resolved product requires the order to carry the same product")
    if product is None:
        return
    if product_resolution is None:
        raise ValueError("a resolved product requires a validated product selection resolution")
    if not isinstance(product_resolution, ProductSelectionResolution):
        raise ValueError("product selection resolution has an unsupported type")
    if product_resolution.product != product:
        raise ValueError("product selection resolution does not match the resolved product")
    if product_resolution.market != execution_context.market:
        raise ValueError("product selection resolution market does not match the execution context")
    if product_resolution.market_pack_id != execution_context.market_pack_id:
        raise ValueError(
            "product selection resolution market-pack id does not match the execution context"
        )
    if product_resolution.rule_version != execution_context.rule_version:
        raise ValueError(
            "product selection resolution rule version does not match the execution context"
        )


def validate_position_effect_fields(
    order: Order,
    *,
    execution_context: ExecutionContext,
    product: ProductCode | None = None,
    position_effect: PositionEffect | None,
    effective_position_effect: PositionEffect | None,
    position_evidence_cut: datetime | None,
    position_evidence: PositionEvidence | None,
    position_evidence_max_age: timedelta | None,
    position_effect_approval_instant: datetime | None,
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None,
) -> None:
    """Fail closed unless the recorded effect semantics are coherent.

    OPEN and absent effects need no evidence and no approval instant. CLOSE
    and AUTO must carry the authoritative evidence, the freshness policy, and
    the approval instant used before approval, and the effective effect is
    re-resolved here so a forged effective value or evidence cut can never be
    recorded. An absent effect may only resolve through a documented,
    versioned market-pack rule: to OPEN (which requires the rule identity on
    the context) or to no effect at all.
    """
    if position_effect is not None and position_effect not in {
        PositionEffect.OPEN,
        PositionEffect.CLOSE,
        PositionEffect.AUTO,
    }:
        raise ValueError("position_effect must be OPEN, CLOSE, AUTO, or None")
    if order.position_effect is not None:
        if position_effect is None:
            raise ValueError("the request must carry the requested position effect from the order")
        if position_effect is not order.position_effect:
            raise ValueError("the request position effect does not match the order position effect")
    elif position_effect is not None:
        # Symmetric with the branch above: the order is the executed
        # contract, so the request may not claim an effect the order does
        # not carry.
        raise ValueError("the request position effect requires the order to carry the same effect")
    if position_effect_approval_instant is not None:
        if not isinstance(position_effect_approval_instant, datetime):
            raise ValueError("the position effect approval instant must be a datetime")
        if (
            position_effect_approval_instant.tzinfo is None
            or position_effect_approval_instant.utcoffset() is None
        ):
            raise ValueError("the position effect approval instant must be timezone-aware")
    if position_evidence_cut is not None and (
        position_evidence_cut.tzinfo is None or position_evidence_cut.utcoffset() is None
    ):
        raise ValueError("position evidence cut must be timezone-aware")
    if effective_position_effect is not None and effective_position_effect not in {
        PositionEffect.OPEN,
        PositionEffect.CLOSE,
    }:
        raise ValueError("resolved position effect must be OPEN or CLOSE")

    if position_effect is not None and position_effect_policy_resolution is not None:
        raise ValueError(
            "a position-effect policy resolution is only valid for an absent position effect"
        )
    if position_effect is None:
        if position_effect_policy_resolution is None:
            raise ValueError(
                "an absent position effect requires a validated market-pack policy resolution"
            )
        if not isinstance(position_effect_policy_resolution, AbsentPositionEffectResolution):
            raise ValueError("position-effect policy resolution has an unsupported type")
        if position_effect_policy_resolution.market != execution_context.market:
            raise ValueError(
                "position-effect policy resolution market does not match the execution context"
            )
        if position_effect_policy_resolution.market_pack_id != execution_context.market_pack_id:
            raise ValueError(
                "position-effect policy resolution market-pack id does not match "
                "the execution context"
            )
        if position_effect_policy_resolution.rule_version != execution_context.rule_version:
            raise ValueError(
                "position-effect policy resolution rule version does not match "
                "the execution context"
            )
        if position_effect_policy_resolution.product != product:
            raise ValueError(
                "position-effect policy resolution product does not match the resolved product"
            )
        if position_effect_policy_resolution.effective is not effective_position_effect:
            raise ValueError(
                "position-effect policy resolution does not match the resolved effective effect"
            )

    if position_effect is PositionEffect.OPEN:
        if (
            position_evidence_cut is not None
            or position_evidence is not None
            or position_evidence_max_age is not None
        ):
            raise ValueError("position evidence is only valid for AUTO or CLOSE position effects")
        if effective_position_effect is not None:
            raise ValueError(
                "an effective position effect is only valid for AUTO or CLOSE requests"
            )
        if position_effect_approval_instant is not None:
            raise ValueError("an approval instant is only valid for AUTO or CLOSE position effects")
        return

    if position_effect is None:
        if (
            position_evidence_cut is not None
            or position_evidence is not None
            or position_evidence_max_age is not None
        ):
            raise ValueError("position evidence is only valid for AUTO or CLOSE position effects")
        if effective_position_effect is not None:
            if effective_position_effect is not PositionEffect.OPEN:
                raise ValueError("an absent position effect may only resolve to OPEN")
            if not (execution_context.market_pack_id or "").strip():
                raise ValueError(
                    "an absent position effect resolved to OPEN requires a market-pack id"
                )
            if not (execution_context.rule_version or "").strip():
                raise ValueError(
                    "an absent position effect resolved to OPEN requires a market-pack rule version"
                )
        if position_effect_approval_instant is not None:
            raise ValueError("an approval instant is only valid for AUTO or CLOSE position effects")
        return

    # CLOSE or AUTO from here on.
    if position_effect is PositionEffect.CLOSE and effective_position_effect is not None:
        if effective_position_effect is not PositionEffect.CLOSE:
            raise ValueError("CLOSE position effect cannot resolve to OPEN")
    if position_effect is PositionEffect.AUTO and effective_position_effect is None:
        raise ValueError(
            "AUTO position effect requires a resolved effective effect (OPEN or CLOSE) "
            "before approval"
        )
    if position_effect_approval_instant is None:
        raise ValueError(
            f"{position_effect.value} position effect requires the approval instant "
            "used for resolution"
        )
    if position_evidence_cut is None:
        raise ValueError(
            f"{position_effect.value} position effect requires the position "
            "evidence cut used for approval"
        )
    if position_evidence is None:
        raise ValueError(
            f"{position_effect.value} position effect requires the authoritative "
            "position evidence used for approval"
        )
    if position_evidence_max_age is None:
        raise ValueError(
            f"{position_effect.value} position effect requires a position evidence freshness policy"
        )
    resolution = resolve_position_effect(
        order,
        evidence=position_evidence,
        max_evidence_age=position_evidence_max_age,
        approval_instant=position_effect_approval_instant,
    )
    if resolution.evidence_cut != position_evidence_cut:
        raise ValueError("position evidence cut does not match the resolved evidence cut")
    if resolution.effective is not effective_position_effect:
        raise ValueError("effective position effect does not match the resolved position effect")


def validate_instrument_resolution(
    order: Order,
    instrument_resolution: InstrumentResolution | None,
) -> None:
    """Fail closed unless any supplied resolution describes the executed instrument.

    The resolution is the point-in-time claim that binds the executed
    ``InstrumentId`` to its selected contract/rule identity. A request can
    never carry a resolution for a different instrument, and the claim is
    authenticated separately by the composed market-pack verifier.
    """
    if instrument_resolution is None:
        return
    if not isinstance(instrument_resolution, InstrumentResolution):
        raise ValueError("instrument resolution has an unsupported type")
    if instrument_resolution.instrument.instrument_id != order.instrument:
        raise ValueError("instrument resolution does not describe the executed instrument")


def validate_risk_resolution_binding(
    risk_result: RiskResult,
    instrument_resolution: InstrumentResolution | None,
) -> None:
    """Fail closed unless the request retains the resolution risk evaluated.

    Risk binds the point-in-time resolution it consumed onto its result. When
    it did, an approved request that carries a different resolution - a
    different contract, a different metadata version, a different rule
    version/effective identity, or different provenance - would execute
    semantics that were never risk approved, and one that drops the
    resolution would hide them. The comparison is therefore the canonical
    resolution identity - instrument facts, contract, rule and contract
    versions, effective instants and provenance - never contract equality,
    and never the resolution instant, which the canonical seam treats as
    provenance rather than identity. A risk result that consumed no
    resolution (legacy request paths) asserts nothing and stays compatible.
    """
    evaluated = risk_result.instrument_resolution
    if evaluated is None:
        return
    if instrument_resolution is None:
        raise ValueError("the approved request must retain the resolution risk evaluated")
    selected = evaluated.identity_payload()
    retained = instrument_resolution.identity_payload()
    if retained != selected:
        raise ValueError("the approved request resolution does not match the risk resolution")


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
    position_effect_approval_instant: datetime | None = None
    product_resolution: ProductSelectionResolution | None = None
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None
    instrument_resolution: InstrumentResolution | None = None

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
            if type(self.order.client_order_id) is not UUID:
                raise ValueError("live execution requires an exact UUID client_order_id")
        validate_instrument_resolution(self.order, self.instrument_resolution)
        validate_risk_resolution_binding(self.risk_result, self.instrument_resolution)
        validate_order_product_symmetry(
            self.order,
            self.product,
            execution_context=self.execution_context,
            product_resolution=self.product_resolution,
        )
        validate_position_effect_fields(
            self.order,
            execution_context=self.execution_context,
            product=self.product,
            position_effect=self.position_effect,
            effective_position_effect=self.effective_position_effect,
            position_evidence_cut=self.position_evidence_cut,
            position_evidence=self.position_evidence,
            position_evidence_max_age=self.position_evidence_max_age,
            position_effect_approval_instant=self.position_effect_approval_instant,
            position_effect_policy_resolution=self.position_effect_policy_resolution,
        )

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
    position_effect_approval_instant: datetime | None = None
    product_resolution: ProductSelectionResolution | None = None
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None
    instrument_resolution: InstrumentResolution | None = None

    def __post_init__(self) -> None:
        validate_instrument_resolution(self.order, self.instrument_resolution)
        validate_order_product_symmetry(
            self.order,
            self.product,
            execution_context=self.execution_context,
            product_resolution=self.product_resolution,
        )
        validate_position_effect_fields(
            self.order,
            execution_context=self.execution_context,
            product=self.product,
            position_effect=self.position_effect,
            effective_position_effect=self.effective_position_effect,
            position_evidence_cut=self.position_evidence_cut,
            position_evidence=self.position_evidence,
            position_evidence_max_age=self.position_evidence_max_age,
            position_effect_approval_instant=self.position_effect_approval_instant,
            position_effect_policy_resolution=self.position_effect_policy_resolution,
        )

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


__all__ = [
    "ApprovedExecutionRequest",
    "PendingExecutionRecoveryRequest",
    "build_order_from_intent",
    "validate_instrument_resolution",
    "validate_order_product_symmetry",
    "validate_position_effect_fields",
    "validate_risk_resolution_binding",
]
