"""Versioned Digital Assets spot market-pack policy configuration."""

from __future__ import annotations

from quantx.domain.policy_verification import MarketPackPolicyVerifier
from quantx.domain.position_effect import PositionEffectPolicy, PositionEffectRule
from quantx.domain.product_selection import ProductSelectionPolicy, ProductSelectionRule
from quantx.domain.value_objects import ProductCode

from .constants import (
    GLOBAL_DIGITAL_ASSETS_MARKET,
    GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
)

DIGITAL_ASSETS_SPOT_PRODUCT = ProductCode("SPOT")

GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION = ProductSelectionPolicy(
    market_pack_id=GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    rule_version=GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
    rules=(
        ProductSelectionRule(
            market=GLOBAL_DIGITAL_ASSETS_MARKET,
            default_product=DIGITAL_ASSETS_SPOT_PRODUCT,
            supported_products=frozenset({DIGITAL_ASSETS_SPOT_PRODUCT}),
        ),
    ),
)

GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT = PositionEffectPolicy(
    market_pack_id=GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    rule_version=GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
    rules=(
        PositionEffectRule(
            market=GLOBAL_DIGITAL_ASSETS_MARKET,
            product=DIGITAL_ASSETS_SPOT_PRODUCT,
            not_applicable=True,
        ),
    ),
)

GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER = MarketPackPolicyVerifier(
    product_selection_policies=(GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION,),
    position_effect_policies=(GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT,),
)

__all__ = [
    "DIGITAL_ASSETS_SPOT_PRODUCT",
    "GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER",
    "GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT",
    "GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION",
]
