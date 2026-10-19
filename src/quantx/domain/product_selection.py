"""Versioned market-pack defaults for omitted per-order products.

A product is a per-order request semantic, never an instrument property and
never inferred from a symbol. Callers may omit it; resolution then requires
an explicit market-pack policy that names the market, default product, and
the stable market-pack/rule identity stamped onto the approved request.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .deployment import ExecutionContext, ExecutionMode
from .instruments import MarketContext
from .value_objects import ProductCode


class ProductSelectionError(ValueError):
    """An omitted product has no authoritative market-pack default."""


@dataclass(frozen=True, slots=True)
class ProductSelectionRule:
    market: MarketContext
    default_product: ProductCode

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketContext):
            raise ValueError("product selection rule market must be a MarketContext")
        if not isinstance(self.default_product, ProductCode):
            raise ValueError("product selection default must be a ProductCode")
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
        if not isinstance(self.market_pack_id, str) or not self.market_pack_id.strip():
            raise ValueError("product selection policy requires a market-pack id")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise ValueError("product selection policy requires a rule version")
        if not self.rules:
            raise ValueError("product selection policy requires at least one market rule")
        if not all(isinstance(rule, ProductSelectionRule) for rule in self.rules):
            raise ValueError("product selection policy rules must be ProductSelectionRule")
        markets = [rule.market for rule in self.rules]
        if len(set(markets)) != len(markets):
            raise ValueError("product selection policy cannot contain duplicate markets")

    def resolve(self, market: MarketContext) -> ProductCode:
        if not isinstance(market, MarketContext):
            raise ProductSelectionError("product selection requires a MarketContext")
        for rule in self.rules:
            if rule.market == market:
                return rule.default_product
        raise ProductSelectionError(
            f"no versioned default product for market {market.venue}/{market.family.value}"
        )


def resolve_request_product(
    context: ExecutionContext,
    *,
    explicit_product: ProductCode | None,
    policy: ProductSelectionPolicy | None,
) -> tuple[ProductCode | None, ExecutionContext]:
    """Resolve one request's product before risk approval, or fail closed.

    This is the single resolution point for the pre-approval stage. An
    explicit product is preserved verbatim and must already carry its own
    market-pack/rule identity: a policy default is never used to justify an
    explicit product. An omitted product is resolved only from the supplied
    versioned market-pack policy, and its identity is bound onto the returned
    execution context.

    Non-live simulated requests may legitimately have no product (absent is
    not a default and not ``AUTO``). LIVE is different: an unresolved product
    cannot be approved, so this function raises before risk or policy runs.

    Conflicting caller configuration is rejected, never overwritten: when a
    context already names a market-pack identity it must match the policy that
    would resolve the product.
    """
    if explicit_product is not None:
        if not isinstance(explicit_product, ProductCode):
            raise ProductSelectionError("explicit product must be a ProductCode")
        if not (context.market_pack_id or "").strip():
            raise ProductSelectionError("an explicit product requires a market-pack id")
        if not (context.rule_version or "").strip():
            raise ProductSelectionError("an explicit product requires a market-pack rule version")
        return explicit_product, context

    if policy is None:
        if context.execution_mode is ExecutionMode.LIVE:
            raise ProductSelectionError(
                "live execution requires a resolved product from a versioned "
                "market-pack selection policy"
            )
        return None, context

    if not isinstance(policy, ProductSelectionPolicy):
        raise ProductSelectionError("product selection policy has an unsupported type")
    if (context.market_pack_id or "").strip() and context.market_pack_id != policy.market_pack_id:
        raise ProductSelectionError(
            "execution context market-pack id conflicts with the product selection policy"
        )
    if (context.rule_version or "").strip() and context.rule_version != policy.rule_version:
        raise ProductSelectionError(
            "execution context rule version conflicts with the product selection policy"
        )
    product = policy.resolve(context.market)
    return product, replace(
        context,
        market_pack_id=policy.market_pack_id,
        rule_version=policy.rule_version,
    )


__all__ = [
    "ProductSelectionError",
    "ProductSelectionPolicy",
    "ProductSelectionRule",
    "resolve_request_product",
]
