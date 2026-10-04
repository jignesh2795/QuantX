"""Versioned venue rule snapshots for India-market compatibility checks.

Exchange rules arrive as data, not code: quantity freezes, operating
ranges/price bands, and allowed order-type / time-in-force / product sets
are supplied per venue snapshot with explicit version, provenance, and
effective time. The engine never invents a missing value — absent or
incoherent rule data fails closed downstream instead of becoming approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantx.domain.enums import OrderType, TimeInForce

from .domain import ProductType


@dataclass(frozen=True, slots=True)
class PriceBandRuleSnapshot:
    """One venue price-band / operating-range rule for an instrument class."""

    lower_bound: Decimal | None
    upper_bound: Decimal | None
    rule_type: str
    effective_at: datetime
    source: str
    version: str

    def __post_init__(self) -> None:
        if not self.rule_type.strip():
            raise ValueError("rule_type must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class IndiaVenueRuleSnapshot:
    """Versioned venue rule data governing one compatibility evaluation.

    Every field except identity metadata is optional: ``None`` means the
    venue did not supply that rule, and any check requiring it fails closed
    with ``INDIA_RULE_DATA_UNAVAILABLE`` rather than assuming permission.
    """

    version: str
    provenance: str
    effective_at: datetime
    allowed_order_types: frozenset[OrderType] | None = None
    allowed_time_in_force: frozenset[TimeInForce] | None = None
    allowed_products: frozenset[ProductType] | None = None
    quantity_freeze: Decimal | None = None
    price_band: PriceBandRuleSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if not self.provenance.strip():
            raise ValueError("provenance must not be empty")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")


__all__ = ["IndiaVenueRuleSnapshot", "PriceBandRuleSnapshot"]
