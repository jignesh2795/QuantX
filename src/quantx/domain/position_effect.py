"""Position-effect resolution against authoritative position evidence.

CLOSE and AUTO are request semantics that need an authoritative position
observation before approval. The observation is bound to a caller-supplied
evidence cut, approval instant, and freshness policy; this module never
invents any of them. OPEN and absent effects need no position evidence, and
absent stays distinct from AUTO. An absent effect resolves only through an
explicit versioned market-pack rule: a documented OPEN default or an explicit
not-applicable declaration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from .deployment import ExecutionContext
from .enums import OrderSide, PositionEffect
from .instruments import MarketContext
from .orders import Order
from .value_objects import InstrumentId, ProductCode


@dataclass(frozen=True, slots=True)
class PositionEvidence:
    """One authoritative position observation used for effect resolution.

    ``matched`` means local and broker observations reconciled to the same
    quantity at this evidence cut. Unmatched, missing, or stale evidence is
    never a resolution input.
    """

    instrument: InstrumentId
    quantity: Decimal
    observed_at: datetime
    evidence_cut: datetime
    matched: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.quantity, Decimal)
            or isinstance(self.quantity, bool)
            or not self.quantity.is_finite()
        ):
            raise ValueError("position evidence quantity must be a finite Decimal")
        # Reconciliation authority is a typed contract: a truthy string or
        # integer must never stand in for the boolean match decision.
        if not isinstance(self.matched, bool):
            raise ValueError("position evidence matched must be boolean")
        for name in ("observed_at", "evidence_cut"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"position evidence {name} must be timezone-aware")
        if self.observed_at > self.evidence_cut:
            raise ValueError("position evidence cannot be observed after the evidence cut")


@dataclass(frozen=True, slots=True)
class PositionEffectResolution:
    """Resolved effect plus the exact evidence cut and approval instant used."""

    requested: PositionEffect | None
    effective: PositionEffect | None
    evidence_cut: datetime | None
    approval_instant: datetime | None = None
    policy_resolution: AbsentPositionEffectResolution | None = None

    def __post_init__(self) -> None:
        if self.policy_resolution is None:
            return
        if self.requested is not None:
            raise ValueError(
                "a position-effect policy resolution is only valid for an absent effect"
            )
        if self.evidence_cut is not None or self.approval_instant is not None:
            raise ValueError(
                "an absent position effect cannot carry position evidence or an approval instant"
            )
        if self.effective is not self.policy_resolution.effective:
            raise ValueError("position-effect policy resolution does not match the resolved effect")


class PositionEffectPolicyError(ValueError):
    """An absent position effect has no authoritative market-pack rule."""


@dataclass(frozen=True, slots=True)
class AbsentPositionEffectResolution:
    """Validated proof that a versioned policy permitted one absent effect.

    The proof records the exact market/product scope and the rule that
    applies. A not-applicable rule yields no effective effect; a documented
    default can only yield OPEN. The approved-request boundary revalidates the
    proof against the request context, product, and recorded effective effect.
    """

    market: MarketContext
    product: ProductCode | None
    rule_product: ProductCode | None
    market_pack_id: str
    rule_version: str
    effective: PositionEffect | None
    not_applicable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketContext):
            raise ValueError("position-effect policy resolution market must be a MarketContext")
        if self.product is not None and not isinstance(self.product, ProductCode):
            raise ValueError("position-effect policy resolution product must be a ProductCode")
        if self.rule_product is not None and not isinstance(self.rule_product, ProductCode):
            raise ValueError("position-effect policy resolution rule product must be a ProductCode")
        if self.rule_product is not None and self.product != self.rule_product:
            raise ValueError(
                "position-effect policy resolution rule product does not match the request product"
            )
        if not isinstance(self.market_pack_id, str) or not self.market_pack_id.strip():
            raise ValueError("position-effect policy resolution requires a market-pack id")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise ValueError("position-effect policy resolution requires a rule version")
        if not isinstance(self.not_applicable, bool):
            raise ValueError("position-effect policy resolution not_applicable must be boolean")
        if self.not_applicable:
            if self.effective is not None:
                raise ValueError(
                    "a not-applicable position-effect policy resolution cannot have an effect"
                )
        elif self.effective is not PositionEffect.OPEN:
            raise ValueError(
                "a position-effect policy resolution must be not applicable or default to OPEN"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "market": self.market.to_payload(),
            "product": None if self.product is None else str(self.product),
            "rule_product": None if self.rule_product is None else str(self.rule_product),
            "market_pack_id": self.market_pack_id,
            "rule_version": self.rule_version,
            "effective": None if self.effective is None else self.effective.value,
            "not_applicable": self.not_applicable,
        }

    @classmethod
    def from_payload(cls, payload: object) -> AbsentPositionEffectResolution:
        if not isinstance(payload, dict):
            raise ValueError("position-effect policy resolution must be an object")
        if set(payload) != {
            "market",
            "product",
            "rule_product",
            "market_pack_id",
            "rule_version",
            "effective",
            "not_applicable",
        }:
            raise ValueError("position-effect policy resolution has unexpected fields")
        product = payload["product"]
        rule_product = payload["rule_product"]
        market_pack_id = payload["market_pack_id"]
        rule_version = payload["rule_version"]
        effective = payload["effective"]
        not_applicable = payload["not_applicable"]
        if product is not None and not isinstance(product, str):
            raise ValueError("position-effect policy resolution product must be a string")
        if rule_product is not None and not isinstance(rule_product, str):
            raise ValueError("position-effect policy resolution rule product must be a string")
        if not isinstance(market_pack_id, str) or not isinstance(rule_version, str):
            raise ValueError("position-effect policy resolution identity must be strings")
        if effective is not None and not isinstance(effective, str):
            raise ValueError("position-effect policy resolution effective must be a string")
        if not isinstance(not_applicable, bool):
            raise ValueError("position-effect policy resolution not_applicable must be boolean")
        return cls(
            market=MarketContext.from_payload(payload["market"]),
            product=None if product is None else ProductCode(product),
            rule_product=None if rule_product is None else ProductCode(rule_product),
            market_pack_id=market_pack_id,
            rule_version=rule_version,
            effective=None if effective is None else PositionEffect(effective),
            not_applicable=not_applicable,
        )


@dataclass(frozen=True, slots=True)
class PositionEffectRule:
    """One documented handling of an absent position effect for a market.

    Exactly one of ``default_effect`` or ``not_applicable`` must be declared.
    A documented default may only be OPEN: CLOSE and AUTO need authoritative
    position evidence and can never be a default. ``product`` optionally
    narrows the rule to one resolved product; ``None`` applies market-wide.
    """

    market: MarketContext
    product: ProductCode | None = None
    default_effect: PositionEffect | None = None
    not_applicable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketContext):
            raise ValueError("position effect rule market must be a MarketContext")
        if self.product is not None:
            if not isinstance(self.product, ProductCode) or not str(self.product).strip():
                raise ValueError("position effect rule product must be a non-empty ProductCode")
        if not isinstance(self.not_applicable, bool):
            raise ValueError("position effect rule not_applicable must be boolean")
        if self.not_applicable:
            if self.default_effect is not None:
                raise ValueError(
                    "position effect rule declares either a default effect or not_applicable"
                )
        elif self.default_effect is None:
            raise ValueError(
                "position effect rule requires a default effect or a not-applicable declaration"
            )
        elif self.default_effect is not PositionEffect.OPEN:
            raise ValueError("an absent position effect may only default to OPEN")


@dataclass(frozen=True, slots=True)
class PositionEffectPolicy:
    """Explicit, versioned absent-effect rules for one market pack.

    The policy is the only source for resolving an absent position effect. It
    never infers one from the instrument, side, or a mutable broker mapping,
    and it carries no implicit fallback when a market/product has no rule.
    """

    market_pack_id: str
    rule_version: str
    rules: tuple[PositionEffectRule, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.market_pack_id, str) or not self.market_pack_id.strip():
            raise ValueError("position effect policy requires a market-pack id")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise ValueError("position effect policy requires a rule version")
        if not self.rules:
            raise ValueError("position effect policy requires at least one market rule")
        if not all(isinstance(rule, PositionEffectRule) for rule in self.rules):
            raise ValueError("position effect policy rules must be PositionEffectRule")
        scopes = [(rule.market, rule.product) for rule in self.rules]
        if len(set(scopes)) != len(scopes):
            raise ValueError("position effect policy cannot contain duplicate rule scopes")

    def resolve(self, market: MarketContext, product: ProductCode | None) -> PositionEffectRule:
        """Return the rule for one market/product scope, or fail closed.

        A product-scoped rule applies only to that exact resolved product; the
        market-wide rule (``product is None``) applies to any product and is
        used only when no exact product rule exists.
        """
        if not isinstance(market, MarketContext):
            raise PositionEffectPolicyError("position effect resolution requires a MarketContext")
        if product is not None and not isinstance(product, ProductCode):
            raise PositionEffectPolicyError(
                "position effect resolution product must be a ProductCode"
            )
        market_wide: PositionEffectRule | None = None
        for rule in self.rules:
            if rule.market != market:
                continue
            if rule.product is None:
                market_wide = rule
            elif product is not None and rule.product == product:
                return rule
        if market_wide is not None:
            return market_wide
        product_label = "absent" if product is None else str(product)
        raise PositionEffectPolicyError(
            "no versioned position-effect rule for market "
            f"{market.venue}/{market.family.value} and product {product_label}"
        )


def resolve_absent_position_effect(
    context: ExecutionContext,
    *,
    product: ProductCode | None,
    policy: PositionEffectPolicy | None,
) -> tuple[PositionEffectResolution, ExecutionContext]:
    """Resolve an absent position effect from a versioned market-pack rule.

    Absent is not a universal default and not ``AUTO``: without an explicit
    policy the request fails closed. The resolved rule binds its market-pack
    and rule identity onto the returned execution context so the approved
    request records which documented rule allowed the absence.
    """
    if policy is None:
        raise PositionEffectPolicyError(
            "an absent position effect requires a versioned market-pack position-effect policy"
        )
    if not isinstance(policy, PositionEffectPolicy):
        raise PositionEffectPolicyError("position effect policy has an unsupported type")
    if (context.market_pack_id or "").strip() and context.market_pack_id != policy.market_pack_id:
        raise PositionEffectPolicyError(
            "execution context market-pack id conflicts with the position effect policy"
        )
    if (context.rule_version or "").strip() and context.rule_version != policy.rule_version:
        raise PositionEffectPolicyError(
            "execution context rule version conflicts with the position effect policy"
        )
    rule = policy.resolve(context.market, product)
    bound = replace(
        context,
        market_pack_id=policy.market_pack_id,
        rule_version=policy.rule_version,
    )
    effective = None if rule.not_applicable else PositionEffect.OPEN
    proof = AbsentPositionEffectResolution(
        market=context.market,
        product=product,
        rule_product=rule.product,
        market_pack_id=policy.market_pack_id,
        rule_version=policy.rule_version,
        effective=effective,
        not_applicable=rule.not_applicable,
    )
    return PositionEffectResolution(None, effective, None, None, proof), bound


def resolve_position_effect(
    order: Order,
    *,
    evidence: PositionEvidence | None,
    max_evidence_age: timedelta,
    approval_instant: datetime | None = None,
) -> PositionEffectResolution:
    """Resolve ``order.position_effect`` deterministically or fail closed.

    ``max_evidence_age`` and the approval instant are mandatory for CLOSE and
    AUTO and caller/market-pack supplied; this function has no freshness
    default. Evidence may not be observed or cut after the approval instant,
    and its age is measured against that instant, so a resolution can never be
    approved from evidence that is stale or future-dated at approval time.
    CLOSE must reduce an existing opposite position and may never cross
    through zero. AUTO resolves to CLOSE only for a reducing order within the
    observed position and otherwise resolves to OPEN; an oversized reducing
    AUTO order fails closed rather than reversing.
    """
    if not isinstance(max_evidence_age, timedelta):
        raise ValueError("max_evidence_age must be a timedelta")
    if max_evidence_age < timedelta(0):
        raise ValueError("max_evidence_age cannot be negative")
    if approval_instant is not None:
        if not isinstance(approval_instant, datetime):
            raise ValueError("approval instant must be a datetime")
        if approval_instant.tzinfo is None or approval_instant.utcoffset() is None:
            raise ValueError("approval instant must be timezone-aware")

    requested = order.position_effect
    if requested is None or requested is PositionEffect.OPEN:
        # Symmetric with the approved-request contract: evidence and an
        # approval instant are only meaningful for CLOSE/AUTO. Accepting and
        # ignoring them here would let a caller believe OPEN was reconciled
        # against unsupported evidence.
        if evidence is not None:
            raise ValueError("position evidence is only valid for AUTO or CLOSE position effects")
        if approval_instant is not None:
            raise ValueError("an approval instant is only valid for AUTO or CLOSE position effects")
        return PositionEffectResolution(requested, requested, None)
    if requested not in {PositionEffect.CLOSE, PositionEffect.AUTO}:
        raise ValueError("position_effect must be OPEN, CLOSE, AUTO, or None")
    if evidence is None:
        raise ValueError(
            f"{requested.value} position effect requires authoritative position evidence"
        )
    if approval_instant is None:
        raise ValueError(
            f"{requested.value} position effect requires the approval instant used for resolution"
        )
    if evidence.instrument != order.instrument:
        raise ValueError("position evidence instrument does not match the order instrument")
    if not evidence.matched:
        raise ValueError("position evidence is not an authoritative reconciled observation")
    if evidence.observed_at > approval_instant:
        raise ValueError("position evidence is observed after the approval instant")
    if evidence.evidence_cut > approval_instant:
        raise ValueError("position evidence cut is after the approval instant")
    if approval_instant - evidence.observed_at > max_evidence_age:
        raise ValueError("position evidence is stale at the approval instant")

    position = evidence.quantity
    if requested is PositionEffect.CLOSE:
        _require_reducing(order, position)
        return PositionEffectResolution(
            requested, PositionEffect.CLOSE, evidence.evidence_cut, approval_instant
        )

    if position == 0:
        return PositionEffectResolution(
            requested, PositionEffect.OPEN, evidence.evidence_cut, approval_instant
        )
    if _reduces_position(order, position):
        _require_reducing(order, position)
        return PositionEffectResolution(
            requested, PositionEffect.CLOSE, evidence.evidence_cut, approval_instant
        )
    return PositionEffectResolution(
        requested, PositionEffect.OPEN, evidence.evidence_cut, approval_instant
    )


def _reduces_position(order: Order, position: Decimal) -> bool:
    if order.side is OrderSide.BUY:
        return position < 0
    return position > 0


def _require_reducing(order: Order, position: Decimal) -> None:
    if position == 0:
        raise ValueError("CLOSE position effect requires an existing opposite position")
    if not _reduces_position(order, position):
        raise ValueError("CLOSE position effect must reduce an existing opposite position")
    if order.quantity > abs(position):
        raise ValueError("CLOSE position effect must not cross through zero")


__all__ = [
    "AbsentPositionEffectResolution",
    "PositionEffectPolicy",
    "PositionEffectPolicyError",
    "PositionEffectResolution",
    "PositionEffectRule",
    "PositionEvidence",
    "resolve_absent_position_effect",
    "resolve_position_effect",
]
