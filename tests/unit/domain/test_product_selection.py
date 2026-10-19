"""QX-04: versioned market-pack product selection and pre-approval resolution."""

from __future__ import annotations

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.product_selection import (
    ProductSelectionError,
    ProductSelectionPolicy,
    ProductSelectionRule,
    resolve_request_product,
)
from quantx.domain.value_objects import ProductCode

NSE_EQUITY = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
BSE_EQUITY = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
NSE_FNO = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")


def _context(
    *,
    market: MarketContext = NSE_EQUITY,
    mode: ExecutionMode = ExecutionMode.PAPER,
    market_pack_id: str | None = None,
    rule_version: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=mode,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


def _policy(*, default: str = "CNC") -> ProductSelectionPolicy:
    return ProductSelectionPolicy(
        market_pack_id="india-equity",
        rule_version="india-products-v1",
        rules=(ProductSelectionRule(NSE_EQUITY, ProductCode(default)),),
    )


def test_policy_resolves_its_configured_market() -> None:
    assert _policy().resolve(NSE_EQUITY) == ProductCode("CNC")


def test_policy_rejects_a_market_without_a_rule() -> None:
    with pytest.raises(ProductSelectionError, match="no versioned default product"):
        _policy().resolve(BSE_EQUITY)


def test_policy_rejects_duplicate_markets() -> None:
    with pytest.raises(ValueError, match="duplicate markets"):
        ProductSelectionPolicy(
            market_pack_id="india-equity",
            rule_version="v1",
            rules=(
                ProductSelectionRule(NSE_EQUITY, ProductCode("CNC")),
                ProductSelectionRule(NSE_EQUITY, ProductCode("MIS")),
            ),
        )


def test_policy_requires_stable_identity_and_rules() -> None:
    with pytest.raises(ValueError, match="market-pack id"):
        ProductSelectionPolicy(
            market_pack_id=" ",
            rule_version="v1",
            rules=(ProductSelectionRule(NSE_EQUITY, ProductCode("CNC")),),
        )
    with pytest.raises(ValueError, match="rule version"):
        ProductSelectionPolicy(
            market_pack_id="india-equity",
            rule_version="",
            rules=(ProductSelectionRule(NSE_EQUITY, ProductCode("CNC")),),
        )
    with pytest.raises(ValueError, match="market-pack id"):
        ProductSelectionPolicy(
            market_pack_id=1,  # type: ignore[arg-type]
            rule_version="v1",
            rules=(ProductSelectionRule(NSE_EQUITY, ProductCode("CNC")),),
        )
    with pytest.raises(ValueError, match="at least one market rule"):
        ProductSelectionPolicy(market_pack_id="india-equity", rule_version="v1", rules=())
    with pytest.raises(ValueError, match="ProductSelectionRule"):
        ProductSelectionPolicy(
            market_pack_id="india-equity",
            rule_version="v1",
            rules=(("NSE", "CNC"),),  # type: ignore[arg-type]
        )


def test_rule_rejects_an_invalid_default() -> None:
    with pytest.raises(ValueError, match="ProductCode"):
        ProductSelectionRule(NSE_EQUITY, "CNC")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MarketContext"):
        ProductSelectionRule("NSE", ProductCode("CNC"))  # type: ignore[arg-type]


def test_omitted_product_resolves_and_binds_pack_identity() -> None:
    product, context = resolve_request_product(_context(), explicit_product=None, policy=_policy())

    assert product == ProductCode("CNC")
    assert context.market_pack_id == "india-equity"
    assert context.rule_version == "india-products-v1"


def test_omitted_product_without_policy_stays_absent_for_simulated_modes() -> None:
    product, context = resolve_request_product(
        _context(mode=ExecutionMode.BACKTEST), explicit_product=None, policy=None
    )

    assert product is None
    assert context == _context(mode=ExecutionMode.BACKTEST)


def test_omitted_live_product_fails_closed_before_risk() -> None:
    with pytest.raises(ProductSelectionError, match="live execution requires a resolved product"):
        resolve_request_product(
            _context(mode=ExecutionMode.LIVE), explicit_product=None, policy=None
        )


def test_omitted_product_fails_closed_when_policy_has_no_rule() -> None:
    with pytest.raises(ProductSelectionError, match="no versioned default product"):
        resolve_request_product(
            _context(market=BSE_EQUITY), explicit_product=None, policy=_policy()
        )


def test_explicit_product_is_preserved_verbatim() -> None:
    context = _context(market_pack_id="india-equity", rule_version="india-products-v1")
    product, resolved = resolve_request_product(
        context,
        explicit_product=ProductCode("MIS"),
        policy=_policy(default="CNC"),
    )

    assert product == ProductCode("MIS")
    assert resolved == context


def test_explicit_product_requires_its_own_pack_identity() -> None:
    with pytest.raises(ProductSelectionError, match="market-pack id"):
        resolve_request_product(_context(), explicit_product=ProductCode("MIS"), policy=None)
    with pytest.raises(ProductSelectionError, match="rule version"):
        resolve_request_product(
            _context(market_pack_id="india-equity"),
            explicit_product=ProductCode("MIS"),
            policy=None,
        )


def test_conflicting_pack_identity_is_rejected_not_overwritten() -> None:
    with pytest.raises(ProductSelectionError, match="market-pack id conflicts"):
        resolve_request_product(
            _context(market_pack_id="other-pack", rule_version="india-products-v1"),
            explicit_product=None,
            policy=_policy(),
        )
    with pytest.raises(ProductSelectionError, match="rule version conflicts"):
        resolve_request_product(
            _context(market_pack_id="india-equity", rule_version="other-version"),
            explicit_product=None,
            policy=_policy(),
        )


def test_matching_existing_identity_is_accepted() -> None:
    context = _context(market_pack_id="india-equity", rule_version="india-products-v1")
    product, resolved = resolve_request_product(context, explicit_product=None, policy=_policy())

    assert product == ProductCode("CNC")
    assert resolved == context


def test_policy_defaults_are_scoped_per_market() -> None:
    policy = ProductSelectionPolicy(
        market_pack_id="india-equity",
        rule_version="v1",
        rules=(
            ProductSelectionRule(NSE_EQUITY, ProductCode("CNC")),
            ProductSelectionRule(NSE_FNO, ProductCode("NRML")),
        ),
    )

    assert policy.resolve(NSE_EQUITY) == ProductCode("CNC")
    assert policy.resolve(NSE_FNO) == ProductCode("NRML")
