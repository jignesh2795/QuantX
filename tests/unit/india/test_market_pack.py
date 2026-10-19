"""QX-04: canonical India market-pack product selection configuration."""

from __future__ import annotations

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.product_selection import ProductSelectionError
from quantx.domain.value_objects import ProductCode
from quantx.india.domain import ProductType
from quantx.india.market_pack import (
    INDIA_EQUITY_COMPATIBILITY_PRODUCT,
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_PRODUCT_SELECTION,
    INDIA_EQUITY_RULE_VERSION,
)

NSE_CASH_EQUITY = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def test_canonical_policy_has_stable_identity() -> None:
    assert INDIA_EQUITY_PRODUCT_SELECTION.market_pack_id == INDIA_EQUITY_MARKET_PACK_ID
    assert INDIA_EQUITY_PRODUCT_SELECTION.rule_version == INDIA_EQUITY_RULE_VERSION
    assert INDIA_EQUITY_MARKET_PACK_ID == "india-equity"
    assert INDIA_EQUITY_RULE_VERSION == "india-products-v1"


def test_nse_cash_equity_preserves_the_established_cnc_default() -> None:
    resolved = INDIA_EQUITY_PRODUCT_SELECTION.resolve(NSE_CASH_EQUITY)

    assert resolved == ProductCode(ProductType.CNC.value)
    assert resolved == INDIA_EQUITY_COMPATIBILITY_PRODUCT


def test_canonical_policy_does_not_invent_defaults_for_other_contexts() -> None:
    bse_equity = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    nse_derivatives = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
    nse_without_country = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE")

    for market in (bse_equity, nse_derivatives, nse_without_country):
        with pytest.raises(ProductSelectionError, match="no versioned default product"):
            INDIA_EQUITY_PRODUCT_SELECTION.resolve(market)


def test_canonical_default_is_the_india_pack_vocabulary() -> None:
    assert INDIA_EQUITY_COMPATIBILITY_PRODUCT.value in {product.value for product in ProductType}
