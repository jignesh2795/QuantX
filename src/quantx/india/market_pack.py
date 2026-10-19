"""Canonical India market-pack product selection for QX-04.

The India pack owns the product vocabulary and any compatibility default.
This module is the one explicit, versioned configuration that a composition
may supply to the pre-approval resolution seam; it is deliberately not a
universal fallback.

Compatibility-default evidence and migration constraint
--------------------------------------------------------
Before QX-04, ``DhanInstrumentRef.product_type`` was the per-instrument
product source. Every repository NSE cash-equity fixture supplied ``CNC``, and
``IndiaExecutionRuleEngine`` permits ``CNC`` for equity/ETF instruments. The
compatibility default below therefore preserves that established NSE
cash-equity behavior only, under a stable pack id and rule version.

No compatibility default is established for BSE cash equity, derivatives,
currency, or commodity contexts. An omitted product in those contexts fails
closed at resolution; it is never inferred from the instrument, symbol, or a
mutable broker mapping. ADR-011 acceptance criterion 7 is therefore claimed
only for the documented NSE cash-equity context.
"""

from __future__ import annotations

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.product_selection import ProductSelectionPolicy, ProductSelectionRule
from quantx.domain.value_objects import ProductCode

from .domain import ProductType

INDIA_EQUITY_MARKET_PACK_ID = "india-equity"
INDIA_EQUITY_RULE_VERSION = "india-products-v1"
INDIA_EQUITY_COMPATIBILITY_PRODUCT = ProductCode(ProductType.CNC.value)

INDIA_EQUITY_PRODUCT_SELECTION = ProductSelectionPolicy(
    market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
    rule_version=INDIA_EQUITY_RULE_VERSION,
    rules=(
        ProductSelectionRule(
            market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
            default_product=INDIA_EQUITY_COMPATIBILITY_PRODUCT,
        ),
    ),
)


__all__ = [
    "INDIA_EQUITY_COMPATIBILITY_PRODUCT",
    "INDIA_EQUITY_MARKET_PACK_ID",
    "INDIA_EQUITY_PRODUCT_SELECTION",
    "INDIA_EQUITY_RULE_VERSION",
]
