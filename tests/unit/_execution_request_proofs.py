"""Test-only constructors for validated execution-request proofs.

These helpers mirror the production resolution path instead of replacing it:
a request built here resolves its product through a versioned market-pack
product-selection policy and its absent position effect through a versioned
market-pack position-effect policy, so the proofs it carries are exactly the
proofs the trusted policies authenticate. A test that needs a *forged* proof
builds the proof value directly and asserts that the request or recovery
boundary rejects it.

Two market packs are trusted in the test suite:

* the canonical India NSE equity pack (``india-equity`` / ``india-products-v1``),
  which is the production configuration and the subject of the forgery
  regressions; and
* a test pack (``test-pack`` / ``test-v1``) that covers the other markets the
  suite exercises, so a request for a market the India pack does not own is
  still authenticated by an explicit, versioned rule instead of by a claim.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.policy_verification import MarketPackPolicyVerifier
from quantx.domain.position_effect import (
    AbsentPositionEffectResolution,
    PositionEffect,
    PositionEffectPolicy,
    PositionEffectRule,
    resolve_absent_position_effect,
)
from quantx.domain.product_selection import (
    ProductSelectionPolicy,
    ProductSelectionResolution,
    ProductSelectionRule,
    resolve_request_product,
)
from quantx.domain.value_objects import ProductCode
from quantx.india.market_pack import (
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_POSITION_EFFECT_POLICY,
    INDIA_EQUITY_PRODUCT_SELECTION,
    INDIA_EQUITY_RULE_VERSION,
)

_REQUEST_FIELDS = tuple(inspect.signature(ApprovedExecutionRequest).parameters)

TEST_MARKET_PACK_ID = "test-pack"
TEST_RULE_VERSION = "test-v1"

_TEST_MARKETS = (
    MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"),
    MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US"),
) + tuple(MarketContext(MarketRegion.INDIA, family, "NSE", "IN") for family in MarketFamily)

_TEST_SUPPORTED_PRODUCTS = frozenset(
    ProductCode(name) for name in ("CNC", "DELIVERY", "MIS", "DEFAULT", "INTRADAY", "MTF")
)

TEST_PRODUCT_SELECTION = ProductSelectionPolicy(
    market_pack_id=TEST_MARKET_PACK_ID,
    rule_version=TEST_RULE_VERSION,
    rules=tuple(
        ProductSelectionRule(
            market=market,
            default_product=ProductCode("CNC"),
            supported_products=_TEST_SUPPORTED_PRODUCTS,
        )
        for market in _TEST_MARKETS
    ),
)

TEST_POSITION_EFFECT_POLICY = PositionEffectPolicy(
    market_pack_id=TEST_MARKET_PACK_ID,
    rule_version=TEST_RULE_VERSION,
    rules=tuple(PositionEffectRule(market=market, not_applicable=True) for market in _TEST_MARKETS),
)

INDIA_EQUITY_POLICY_VERIFIER = MarketPackPolicyVerifier(
    product_selection_policies=(INDIA_EQUITY_PRODUCT_SELECTION, TEST_PRODUCT_SELECTION),
    position_effect_policies=(INDIA_EQUITY_POSITION_EFFECT_POLICY, TEST_POSITION_EFFECT_POLICY),
)

__all__ = [
    "INDIA_EQUITY_POLICY_VERIFIER",
    "TEST_MARKET_PACK_ID",
    "TEST_RULE_VERSION",
    "approved_request",
    "policy_verifier",
]


def policy_verifier() -> MarketPackPolicyVerifier:
    """The canonical verifier a deployment composes for the trusted packs."""
    return INDIA_EQUITY_POLICY_VERIFIER


def _policies_for(context: Any) -> tuple[ProductSelectionPolicy, PositionEffectPolicy]:
    """Return the trusted policy pair that owns one execution context."""
    if (
        context.market_pack_id == INDIA_EQUITY_MARKET_PACK_ID
        and context.rule_version == INDIA_EQUITY_RULE_VERSION
    ):
        return INDIA_EQUITY_PRODUCT_SELECTION, INDIA_EQUITY_POSITION_EFFECT_POLICY
    return TEST_PRODUCT_SELECTION, TEST_POSITION_EFFECT_POLICY


def product_resolution(
    context: Any,
    product: ProductCode,
) -> ProductSelectionResolution:
    """Resolve one product proof through the trusted selection policy."""
    selection_policy, _ = _policies_for(context)
    selection = resolve_request_product(
        context,
        explicit_product=product,
        policy=selection_policy,
    )
    assert selection.resolution is not None
    return selection.resolution


def absent_effect_resolution(
    context: Any,
    *,
    product: ProductCode | None = None,
    effective: PositionEffect | None = None,
) -> AbsentPositionEffectResolution:
    """Resolve one absent-effect proof through the trusted position-effect policy."""
    _, effect_policy = _policies_for(context)
    resolution, _ = resolve_absent_position_effect(
        context,
        product=product,
        policy=effect_policy,
    )
    if effective is not None and effective is not resolution.effective:
        raise ValueError("the trusted policy does not resolve that effective effect")
    assert resolution.policy_resolution is not None
    return resolution.policy_resolution


def approved_request(*args: Any, **kwargs: Any) -> ApprovedExecutionRequest:
    """Build a request whose proofs the trusted policies authenticate.

    The product is resolved through the trusted market-pack selection policy
    and the absent position effect through the trusted position-effect policy,
    exactly as the pre-approval seam does. Negative tests that intentionally
    omit or forge a proof must call ``ApprovedExecutionRequest`` directly.
    """
    order = kwargs.get("order", args[0] if args else None)
    context = kwargs.get("execution_context", args[1] if len(args) > 1 else None)
    if context is None:
        raise ValueError("approved_request requires an execution context")
    product = kwargs.get("product")
    if product is None and order is not None:
        product = getattr(order, "product", None)
    selection_policy, effect_policy = _policies_for(context)
    selection = resolve_request_product(
        context,
        explicit_product=product,
        policy=selection_policy,
    )
    resolved_product = selection.product
    assert resolved_product is not None
    bound_context = selection.context
    if order is not None and getattr(order, "product", None) is None:
        order = replace(order, product=resolved_product)
    position_effect = kwargs.get("position_effect")
    if position_effect is None and order is not None:
        position_effect = getattr(order, "position_effect", None)
    fields = dict(zip(_REQUEST_FIELDS, args, strict=False))
    fields.update(kwargs)
    fields["order"] = order
    fields["execution_context"] = bound_context
    fields["product"] = resolved_product
    if position_effect is None:
        effect_resolution, _ = resolve_absent_position_effect(
            bound_context,
            product=resolved_product,
            policy=effect_policy,
        )
        assert effect_resolution.policy_resolution is not None
        fields.setdefault(
            "position_effect_policy_resolution",
            effect_resolution.policy_resolution,
        )
    else:
        fields.setdefault("position_effect", position_effect)
    fields.setdefault("product_resolution", selection.resolution)
    return ApprovedExecutionRequest(**fields)
