"""QX-04: canonical India market-pack product selection configuration."""

from __future__ import annotations

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.position_effect import (
    PositionEffectPolicyError,
    resolve_absent_position_effect,
)
from quantx.domain.product_selection import ProductSelectionError
from quantx.domain.value_objects import ProductCode
from quantx.india.domain import ProductType
from quantx.india.execution_rules import india_supported_products
from quantx.india.market_pack import (
    INDIA_EQUITY_COMPATIBILITY_PRODUCT,
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_POSITION_EFFECT_POLICY,
    INDIA_EQUITY_PRODUCT_SELECTION,
    INDIA_EQUITY_RULE_VERSION,
    INDIA_EQUITY_SUPPORTED_PRODUCTS,
)

NSE_CASH_EQUITY = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _context(market: MarketContext = NSE_CASH_EQUITY) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("p-1"),
        deployment_id=StrategyDeploymentId("d-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


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


def test_supported_products_match_the_india_universal_matrix() -> None:
    assert INDIA_EQUITY_SUPPORTED_PRODUCTS == frozenset(
        {ProductCode("CNC"), ProductCode("DELIVERY"), ProductCode("MIS")}
    )


def test_supported_products_are_derived_from_the_execution_rule_matrix() -> None:
    assert INDIA_EQUITY_SUPPORTED_PRODUCTS == frozenset(
        ProductCode(product.value) for product in india_supported_products(AssetClass.EQUITY)
    )
    assert india_supported_products(AssetClass.EQUITY) == frozenset(
        {ProductType.CNC, ProductType.DELIVERY, ProductType.MIS}
    )
    assert india_supported_products(AssetClass.FUTURE) == frozenset(
        {ProductType.NRML, ProductType.MIS}
    )


def test_explicit_supported_product_is_validated_by_the_canonical_policy() -> None:
    resolved = INDIA_EQUITY_PRODUCT_SELECTION.resolve_explicit(NSE_CASH_EQUITY, ProductCode("MIS"))

    assert resolved == ProductCode("MIS")


def test_explicit_unsupported_product_fails_closed() -> None:
    with pytest.raises(ProductSelectionError, match="is not supported for market"):
        INDIA_EQUITY_PRODUCT_SELECTION.resolve_explicit(NSE_CASH_EQUITY, ProductCode("NRML"))


def test_canonical_position_effect_policy_is_not_applicable_for_nse_equity() -> None:
    resolution, context = resolve_absent_position_effect(
        _context(),
        product=INDIA_EQUITY_COMPATIBILITY_PRODUCT,
        policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
    )

    assert resolution.effective is None
    assert resolution.evidence_cut is None
    assert resolution.policy_resolution is not None
    assert resolution.policy_resolution.product == INDIA_EQUITY_COMPATIBILITY_PRODUCT
    assert resolution.policy_resolution.rule_product == INDIA_EQUITY_COMPATIBILITY_PRODUCT
    assert resolution.policy_resolution.not_applicable
    assert context.market_pack_id == INDIA_EQUITY_MARKET_PACK_ID
    assert context.rule_version == INDIA_EQUITY_RULE_VERSION


def test_delivery_is_explicitly_not_applicable() -> None:
    resolution, _ = resolve_absent_position_effect(
        _context(),
        product=ProductCode(ProductType.DELIVERY.value),
        policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
    )

    assert resolution.effective is None
    assert resolution.policy_resolution is not None
    assert resolution.policy_resolution.rule_product == ProductCode(ProductType.DELIVERY.value)


def test_mis_absent_effect_does_not_inherit_the_delivery_rule() -> None:
    with pytest.raises(PositionEffectPolicyError, match="no versioned position-effect rule"):
        resolve_absent_position_effect(
            _context(),
            product=ProductCode(ProductType.MIS.value),
            policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
        )


def test_canonical_position_effect_policy_has_no_market_wide_rule() -> None:
    assert all(rule.product is not None for rule in INDIA_EQUITY_POSITION_EFFECT_POLICY.rules)


def test_canonical_position_effect_policy_does_not_invent_rules_for_other_contexts() -> None:
    bse_equity = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")

    with pytest.raises(PositionEffectPolicyError, match="no versioned position-effect rule"):
        resolve_absent_position_effect(
            _context(bse_equity),
            product=None,
            policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
        )
