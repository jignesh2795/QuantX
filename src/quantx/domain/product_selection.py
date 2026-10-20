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
class ProductSelectionResolution:
    """A claim that one versioned policy selected one product.

    The claim names the market, the selected product, and the market-pack and
    rule identity that made the selection. It carries no support set: a
    payload cannot prove its own authenticity. Authenticity is established by
    :meth:`ProductSelectionPolicy.verify_resolution`, which re-derives the
    support decision from the trusted, versioned policy that the approved
    request boundary is composed with.
    """

    market: MarketContext
    product: ProductCode
    market_pack_id: str
    rule_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.market, MarketContext):
            raise ValueError("product selection resolution market must be a MarketContext")
        if not isinstance(self.product, ProductCode) or not str(self.product).strip():
            raise ValueError("product selection resolution product must be a ProductCode")
        if not isinstance(self.market_pack_id, str) or not self.market_pack_id.strip():
            raise ValueError("product selection resolution requires a market-pack id")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise ValueError("product selection resolution requires a rule version")

    def to_payload(self) -> dict[str, object]:
        return {
            "market": self.market.to_payload(),
            "product": str(self.product),
            "market_pack_id": self.market_pack_id,
            "rule_version": self.rule_version,
        }

    @classmethod
    def from_payload(cls, payload: object) -> ProductSelectionResolution:
        if not isinstance(payload, dict):
            raise ValueError("product selection resolution must be an object")
        if set(payload) != {
            "market",
            "product",
            "market_pack_id",
            "rule_version",
        }:
            raise ValueError("product selection resolution has unexpected fields")
        product = payload["product"]
        market_pack_id = payload["market_pack_id"]
        rule_version = payload["rule_version"]
        if not isinstance(product, str):
            raise ValueError("product selection resolution product must be a string")
        if not isinstance(market_pack_id, str) or not isinstance(rule_version, str):
            raise ValueError("product selection resolution identity must be strings")
        return cls(
            market=MarketContext.from_payload(payload["market"]),
            product=ProductCode(product),
            market_pack_id=market_pack_id,
            rule_version=rule_version,
        )


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

    def rule_for(self, market: MarketContext) -> ProductSelectionRule:
        """Return the exact rule for one market, or fail closed."""
        if not isinstance(market, MarketContext):
            raise ProductSelectionError("product selection requires a MarketContext")
        rule = self._find_rule(market)
        if rule is None:
            raise ProductSelectionError(
                "no versioned product selection rule for market "
                f"{market.venue}/{market.family.value}"
            )
        return rule

    def default_rule(self, market: MarketContext) -> ProductSelectionRule:
        """Return the rule that supplies one market's compatibility default."""
        if not isinstance(market, MarketContext):
            raise ProductSelectionError("product selection requires a MarketContext")
        rule = self._find_rule(market)
        if rule is None or rule.default_product is None:
            raise ProductSelectionError(
                f"no versioned default product for market {market.venue}/{market.family.value}"
            )
        return rule

    def resolve(self, market: MarketContext) -> ProductCode:
        rule = self.default_rule(market)
        assert rule.default_product is not None
        return rule.default_product

    def resolve_explicit(self, market: MarketContext, product: ProductCode) -> ProductCode:
        """Validate one explicit product against its market's support set."""
        if not isinstance(product, ProductCode):
            raise ProductSelectionError("explicit product must be a ProductCode")
        rule = self.rule_for(market)
        if not rule.supports(product):
            raise ProductSelectionError(
                f"product {product} is not supported for market "
                f"{market.venue}/{market.family.value}"
            )
        return product

    def verify_resolution(self, resolution: ProductSelectionResolution) -> None:
        """Fail closed unless this policy supports the product a claim names.

        The claim itself proves nothing: it can be written by any caller. This
        check re-derives the support decision from the trusted, versioned
        policy, so a claim naming a product outside the policy's support set,
        a different market pack, a different rule version, or an uncovered
        market is rejected.
        """
        if not isinstance(resolution, ProductSelectionResolution):
            raise ProductSelectionError("product selection resolution has an unsupported type")
        if resolution.market_pack_id != self.market_pack_id:
            raise ProductSelectionError(
                "product selection resolution market-pack id does not match the product policy"
            )
        if resolution.rule_version != self.rule_version:
            raise ProductSelectionError(
                "product selection resolution rule version does not match the product policy"
            )
        rule = self.rule_for(resolution.market)
        if not rule.supports(resolution.product):
            raise ProductSelectionError(
                f"product {resolution.product} is not supported for market "
                f"{resolution.market.venue}/{resolution.market.family.value}"
            )


@dataclass(frozen=True, slots=True)
class ProductSelectionResult:
    """Resolved product, bound context, and the proof that authorized it."""

    product: ProductCode | None
    context: ExecutionContext
    resolution: ProductSelectionResolution | None

    def __post_init__(self) -> None:
        if self.product is None:
            if self.resolution is not None:
                raise ValueError("an absent product cannot carry a product selection resolution")
            if self.context.execution_mode is ExecutionMode.LIVE:
                raise ValueError("live execution requires a resolved product")
            return
        if self.resolution is None:
            raise ValueError("a resolved product requires a product selection resolution")
        if self.resolution.product != self.product:
            raise ValueError("product selection resolution does not match the resolved product")
        if self.resolution.market != self.context.market:
            raise ValueError(
                "product selection resolution market does not match the execution context"
            )
        if self.resolution.market_pack_id != self.context.market_pack_id:
            raise ValueError(
                "product selection resolution market-pack id does not match the execution context"
            )
        if self.resolution.rule_version != self.context.rule_version:
            raise ValueError(
                "product selection resolution rule version does not match the execution context"
            )


def resolve_request_product(
    context: ExecutionContext,
    *,
    explicit_product: ProductCode | None,
    policy: ProductSelectionPolicy | None,
) -> ProductSelectionResult:
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
        rule = policy.rule_for(context.market)
        policy.resolve_explicit(context.market, explicit_product)
        bound_context = replace(
            context,
            market_pack_id=policy.market_pack_id,
            rule_version=policy.rule_version,
        )
        return ProductSelectionResult(
            product=explicit_product,
            context=bound_context,
            resolution=ProductSelectionResolution(
                market=context.market,
                product=explicit_product,
                market_pack_id=policy.market_pack_id,
                rule_version=policy.rule_version,
            ),
        )

    if policy is None:
        if context.execution_mode is ExecutionMode.LIVE:
            raise ProductSelectionError(
                "live execution requires a resolved product from a versioned "
                "market-pack selection policy"
            )
        return ProductSelectionResult(product=None, context=context, resolution=None)

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
    rule = policy.default_rule(context.market)
    product = rule.default_product
    assert product is not None
    bound_context = replace(
        context,
        market_pack_id=policy.market_pack_id,
        rule_version=policy.rule_version,
    )
    return ProductSelectionResult(
        product=product,
        context=bound_context,
        resolution=ProductSelectionResolution(
            market=context.market,
            product=product,
            market_pack_id=policy.market_pack_id,
            rule_version=policy.rule_version,
        ),
    )


__all__ = [
    "ProductSelectionError",
    "ProductSelectionPolicy",
    "ProductSelectionResolution",
    "ProductSelectionResult",
    "ProductSelectionRule",
    "resolve_request_product",
]
