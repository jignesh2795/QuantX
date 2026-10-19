"""Versioned market-pack defaults for omitted per-order products.

A product is a per-order request semantic, never an instrument property and
never inferred from a symbol. Callers may omit it; resolution then requires
an explicit market-pack policy that names the market, default product, and
the stable market-pack/rule identity stamped onto the approved request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .instruments import MarketContext
from .value_objects import ProductCode


class ProductSelectionError(ValueError):
    """An omitted product has no authoritative market-pack default."""


@dataclass(frozen=True, slots=True)
class ProductSelectionRule:
    market: MarketContext
    default_product: ProductCode

    def __post_init__(self) -> None:
        if not str(self.default_product).strip():
            raise ValueError("default product must not be empty")


@dataclass(frozen=True, slots=True)
class ProductSelectionPolicy:
    """Explicit, versioned default-product configuration for one market pack.

    The policy is the only source for resolving an omitted product. It does
    not infer a product from instrument identity, and it carries no implicit
    fallback when a market has no rule.
    """

    market_pack_id: str
    rule_version: str
    rules: tuple[ProductSelectionRule, ...]

    def __post_init__(self) -> None:
        if not self.market_pack_id.strip():
            raise ValueError("product selection policy requires a market-pack id")
        if not self.rule_version.strip():
            raise ValueError("product selection policy requires a rule version")
        if not self.rules:
            raise ValueError("product selection policy requires at least one market rule")
        markets = [rule.market for rule in self.rules]
        if len(set(markets)) != len(markets):
            raise ValueError("product selection policy cannot contain duplicate markets")

    def resolve(self, market: MarketContext) -> ProductCode:
        for rule in self.rules:
            if rule.market == market:
                return rule.default_product
        raise ProductSelectionError(
            f"no versioned default product for market {market.venue}/{market.family.value}"
        )


__all__ = ["ProductSelectionError", "ProductSelectionPolicy", "ProductSelectionRule"]
