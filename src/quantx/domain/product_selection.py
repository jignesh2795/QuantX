"""Versioned market-pack defaults and support for per-order products.

A product is a per-order request semantic, never an instrument property and
never inferred from a symbol. Callers may omit it; resolution then requires
an explicit market-pack policy that names the market, default product, and
the stable market-pack/rule identity stamped onto the approved request. An
explicit product is preserved verbatim only when the same versioned policy
confirms that product is supported for the request market.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .deployment import ExecutionContext, ExecutionMode
from .instruments import MarketContext
from .value_objects import ProductCode


class ProductSelectionError(ValueError):
    """An omitted or explicit product has no authoritative market-pack rule."""


@dataclass(frozen=True, slots=True)
class ProductSelectionRule:
    """Supported products for one market, with an optional compatibility default.

    ``supported_products`` is the authoritative support set. When it is empty
    the rule is a default-only rule and the default is the only supported
    product, which keeps documented compatibility defaults explicit. A rule
    must declare at least one of the two.
    """

    market: MarketContext
    default_product: ProductCode | None = None
    supported_products: frozenset[ProductCode] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketContext):
            raise ValueError("product selection rule market must be a MarketContext")
        if self.default_product is not None:
            if not isinstance(self.default_product, ProductCode):
                raise ValueError("product selection default must be a ProductCode")
            if not str(self.default_product).strip():
                raise ValueError("default product must not be empty")
        if not isinstance(self.supported_products, frozenset):
            raise ValueError("product selection supported products must be a frozenset")
        for product in self.supported_products:
            if not isinstance(product, ProductCode) or not str(product).strip():
                raise ValueError("supported products must be non-empty ProductCode values")
        if self.default_product is None and not self.supported_products:
            raise ValueError(
                "product selection rule requires a default product or supported products"
            )
        if (
            self.default_product is not None
            and self.supported_products
            and self.default_product not in self.supported_products
        ):
            raise ValueError("the default product must be one of the supported products")

    @property
    def effective_supported_products(self) -> frozenset[ProductCode]:
        """The authoritative support set, defaulting to the compatibility default."""
        if self.supported_products:
            return self.supported_products
        if self.default_product is None:
            raise ValueError("product selection rule has no supported products")
        return frozenset({self.default_product})

    def supports(self, product: ProductCode) -> bool:
        return product in self.effective_supported_products


@dataclass(frozen=True, slots=True)
class ProductSelectionPolicy:
    """Explicit, versioned product configuration for one market pack.

    The policy is the only source for resolving an omitted product and for
    validating an explicit one. It does not infer a product from instrument
    identity, and it carries no implicit fallback when a market has no rule.
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

    def _find_rule(self, market: MarketContext) -> ProductSelectionRule | None:
        for rule in self.rules:
            if rule.market == market:
                return rule
        return None

    def resolve(self, market: MarketContext) -> ProductCode:
        if not isinstance(market, MarketContext):
            raise ProductSelectionError("product selection requires a MarketContext")
        rule = self._find_rule(market)
        if rule is None or rule.default_product is None:
            raise ProductSelectionError(
                f"no versioned default product for market {market.venue}/{market.family.value}"
            )
        return rule.default_product

    def resolve_explicit(self, market: MarketContext, product: ProductCode) -> ProductCode:
        """Validate one explicit product against its market's support set."""
        if not isinstance(market, MarketContext):
            raise ProductSelectionError("product selection requires a MarketContext")
        if not isinstance(product, ProductCode):
            raise ProductSelectionError("explicit product must be a ProductCode")
        rule = self._find_rule(market)
        if rule is None:
            raise ProductSelectionError(
                "no versioned product selection rule for market "
                f"{market.venue}/{market.family.value}"
            )
        if not rule.supports(product):
            raise ProductSelectionError(
                f"product {product} is not supported for market "
                f"{market.venue}/{market.family.value}"
            )
        return product


def resolve_request_product(
    context: ExecutionContext,
    *,
    explicit_product: ProductCode | None,
    policy: ProductSelectionPolicy | None,
) -> tuple[ProductCode | None, ExecutionContext]:
    """Resolve one request's product before risk approval, or fail closed.

    This is the single resolution point for the pre-approval stage. An
    explicit product is preserved verbatim only through the same versioned
    market-pack policy that must confirm it is supported for the request
    market; a support check is never inferred from caller-supplied identity
    alone, and a policy default is never used to justify an explicit product.
    An omitted product is resolved only from the supplied versioned
    market-pack policy, and that policy's identity is bound onto the returned
    execution context.

    Non-live simulated requests may legitimately have no product (absent is
    not a default and not ``AUTO``). LIVE is different: an unresolved product
    cannot be approved, so this function raises before risk or policy runs.

    Conflicting caller configuration is rejected, never overwritten: when a
    context already names a market-pack identity it must match the policy that
    resolves or validates the product.
    """
    if explicit_product is not None:
        if not isinstance(explicit_product, ProductCode):
            raise ProductSelectionError("explicit product must be a ProductCode")
        if policy is None:
            raise ProductSelectionError(
                "an explicit product requires a versioned market-pack product selection policy"
            )
        if not isinstance(policy, ProductSelectionPolicy):
            raise ProductSelectionError("product selection policy has an unsupported type")
        if (
            context.market_pack_id or ""
        ).strip() and context.market_pack_id != policy.market_pack_id:
            raise ProductSelectionError(
                "execution context market-pack id conflicts with the product selection policy"
            )
        if (context.rule_version or "").strip() and context.rule_version != policy.rule_version:
            raise ProductSelectionError(
                "execution context rule version conflicts with the product selection policy"
            )
        policy.resolve_explicit(context.market, explicit_product)
        return explicit_product, replace(
            context,
            market_pack_id=policy.market_pack_id,
            rule_version=policy.rule_version,
        )

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
