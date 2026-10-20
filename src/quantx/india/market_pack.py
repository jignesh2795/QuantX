"""Canonical India market-pack product and position-effect configuration.

The India pack owns the product vocabulary, the product support set, any
compatibility default, and the documented handling of an absent position
effect. This module is the one explicit, versioned configuration that a
composition may supply to the pre-approval resolution seams; it is
deliberately not a universal fallback.

Compatibility-default evidence and migration constraint
--------------------------------------------------------
Before QX-04, ``DhanInstrumentRef.product_type`` was the per-instrument
product source. Every repository NSE cash-equity fixture supplied ``CNC``, and
``IndiaExecutionRuleEngine`` permits ``CNC`` for equity/ETF instruments. The
compatibility default below therefore preserves that established NSE
cash-equity behavior only, under a stable pack id and rule version. The
supported set mirrors the execution rule engine's India-universal matrix so an
explicit product can never bypass the one authoritative list.

No compatibility default is established for BSE cash equity, derivatives,
currency, or commodity contexts. An omitted product in those contexts fails
closed at resolution; it is never inferred from the instrument, symbol, or a
mutable broker mapping. ADR-011 acceptance criterion 7 is therefore claimed
only for the documented NSE cash-equity context.

Position effect: the NSE cash-equity position-effect concept is documented
not applicable (equity delivery has no OPEN/CLOSE distinction), so an absent
effect under this pack resolves to no effective effect — never to OPEN — and
the rule identity is still bound to the prepared request.
"""

from __future__ import annotations

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.position_effect import PositionEffectPolicy, PositionEffectRule
from quantx.domain.product_selection import ProductSelectionPolicy, ProductSelectionRule
from quantx.domain.value_objects import ProductCode

from .domain import ProductType
from .execution_rules import india_supported_products

INDIA_EQUITY_MARKET_PACK_ID = "india-equity"
INDIA_EQUITY_RULE_VERSION = "india-products-v1"
INDIA_EQUITY_COMPATIBILITY_PRODUCT = ProductCode(ProductType.CNC.value)
INDIA_EQUITY_SUPPORTED_PRODUCTS = frozenset(
    ProductCode(product.value) for product in india_supported_products(AssetClass.EQUITY)
)

INDIA_EQUITY_MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")

INDIA_EQUITY_PRODUCT_SELECTION = ProductSelectionPolicy(
    market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
    rule_version=INDIA_EQUITY_RULE_VERSION,
    rules=(
        ProductSelectionRule(
            market=INDIA_EQUITY_MARKET,
            default_product=INDIA_EQUITY_COMPATIBILITY_PRODUCT,
            supported_products=INDIA_EQUITY_SUPPORTED_PRODUCTS,
        ),
    ),
)

INDIA_EQUITY_POSITION_EFFECT_POLICY = PositionEffectPolicy(
    market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
    rule_version=INDIA_EQUITY_RULE_VERSION,
    rules=(
        PositionEffectRule(
            market=INDIA_EQUITY_MARKET,
            not_applicable=True,
        ),
    ),
)


__all__ = [
    "INDIA_EQUITY_COMPATIBILITY_PRODUCT",
    "INDIA_EQUITY_MARKET",
    "INDIA_EQUITY_MARKET_PACK_ID",
    "INDIA_EQUITY_POSITION_EFFECT_POLICY",
    "INDIA_EQUITY_PRODUCT_SELECTION",
    "INDIA_EQUITY_RULE_VERSION",
    "INDIA_EQUITY_SUPPORTED_PRODUCTS",
]
