"""Position-effect resolution against authoritative position evidence.

CLOSE and AUTO are request semantics that need an authoritative position
observation before approval. The observation is bound to a caller-supplied
evidence cut and freshness policy; this module never invents either. OPEN
and absent effects need no position evidence, and absent stays distinct
from AUTO.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from quantx.domain.enums import OrderSide, PositionEffect
from quantx.domain.orders import Order
from quantx.domain.value_objects import InstrumentId


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
        for name in ("observed_at", "evidence_cut"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"position evidence {name} must be timezone-aware")
        if self.observed_at > self.evidence_cut:
            raise ValueError("position evidence cannot be observed after the evidence cut")


@dataclass(frozen=True, slots=True)
class PositionEffectResolution:
    """Resolved effect plus the exact evidence cut that produced it."""

    requested: PositionEffect | None
    effective: PositionEffect | None
    evidence_cut: datetime | None


def resolve_position_effect(
    order: Order,
    *,
    evidence: PositionEvidence | None,
    max_evidence_age: timedelta,
) -> PositionEffectResolution:
    """Resolve ``order.position_effect`` deterministically or fail closed.

    ``max_evidence_age`` is mandatory and caller/market-pack supplied; this
    function has no freshness default. CLOSE must reduce an existing
    opposite position and may never cross through zero. AUTO resolves to
    CLOSE only for a reducing order within the observed position and
    otherwise resolves to OPEN; an oversized reducing AUTO order fails
    closed rather than reversing.
    """
    if max_evidence_age < timedelta(0):
        raise ValueError("max_evidence_age cannot be negative")

    requested = order.position_effect
    if requested is None or requested is PositionEffect.OPEN:
        return PositionEffectResolution(requested, requested, None)
    if requested not in {PositionEffect.CLOSE, PositionEffect.AUTO}:
        raise ValueError("position_effect must be OPEN, CLOSE, AUTO, or None")
    if evidence is None:
        raise ValueError(
            f"{requested.value} position effect requires authoritative position evidence"
        )
    if evidence.instrument != order.instrument:
        raise ValueError("position evidence instrument does not match the order instrument")
    if not evidence.matched:
        raise ValueError("position evidence is not an authoritative reconciled observation")
    if evidence.evidence_cut - evidence.observed_at > max_evidence_age:
        raise ValueError("position evidence is stale for the requested position effect")

    position = evidence.quantity
    if requested is PositionEffect.CLOSE:
        _require_reducing(order, position)
        return PositionEffectResolution(requested, PositionEffect.CLOSE, evidence.evidence_cut)

    if position == 0:
        return PositionEffectResolution(requested, PositionEffect.OPEN, evidence.evidence_cut)
    if _reduces_position(order, position):
        _require_reducing(order, position)
        return PositionEffectResolution(requested, PositionEffect.CLOSE, evidence.evidence_cut)
    return PositionEffectResolution(requested, PositionEffect.OPEN, evidence.evidence_cut)


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


__all__ = ["PositionEffectResolution", "PositionEvidence", "resolve_position_effect"]
