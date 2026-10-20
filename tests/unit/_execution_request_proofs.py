"""Test-only constructors for validated execution-request proofs.

These helpers mirror the resolver's output shape without replacing the
production resolution paths. They keep per-file factories focused on the
behaviour under test while still exercising request-boundary validation.
"""

from __future__ import annotations

from typing import Any

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.position_effect import (
    AbsentPositionEffectResolution,
    PositionEffect,
)
from quantx.domain.product_selection import ProductSelectionResolution
from quantx.domain.value_objects import ProductCode


def product_resolution(
    context: Any,
    product: ProductCode,
    *,
    supported_products: frozenset[ProductCode] | None = None,
) -> ProductSelectionResolution:
    return ProductSelectionResolution(
        market=context.market,
        product=product,
        market_pack_id=context.market_pack_id or "",
        rule_version=context.rule_version or "",
        supported_products=supported_products or frozenset({product}),
    )


def absent_effect_resolution(
    context: Any,
    *,
    product: ProductCode | None = None,
    effective: PositionEffect | None = None,
) -> AbsentPositionEffectResolution:
    return AbsentPositionEffectResolution(
        market=context.market,
        product=product,
        rule_product=product,
        market_pack_id=context.market_pack_id or "",
        rule_version=context.rule_version or "",
        effective=effective,
        not_applicable=effective is None,
    )


def approved_request(*args: Any, **kwargs: Any) -> ApprovedExecutionRequest:
    """Build a request with proof kwargs derived from its own fields.

    Negative tests that intentionally omit a proof must call
    ``ApprovedExecutionRequest`` directly.
    """
    order = kwargs.get("order", args[0] if args else None)
    context = kwargs.get("execution_context", args[1] if len(args) > 1 else None)
    if context is None:
        raise ValueError("approved_request requires an execution context")
    product = kwargs.get("product")
    if product is None and order is not None:
        product = getattr(order, "product", None)
    position_effect = kwargs.get("position_effect")
    if position_effect is None and order is not None:
        position_effect = getattr(order, "position_effect", None)
    if product is not None:
        kwargs.setdefault("product_resolution", product_resolution(context, product))
        kwargs.setdefault("product", product)
    if position_effect is None:
        effective = kwargs.get("effective_position_effect")
        proof_effective = effective if effective is PositionEffect.OPEN else None
        kwargs.setdefault(
            "position_effect_policy_resolution",
            absent_effect_resolution(
                context,
                product=product,
                effective=proof_effective,
            ),
        )
    else:
        kwargs.setdefault("position_effect", position_effect)
    return ApprovedExecutionRequest(*args, **kwargs)
