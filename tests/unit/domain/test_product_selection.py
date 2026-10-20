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


def _policy(
    *,
    default: str = "CNC",
    supported: tuple[str, ...] | None = None,
) -> ProductSelectionPolicy:
    if supported is None:
        rule = ProductSelectionRule(NSE_EQUITY, ProductCode(default))
    else:
        rule = ProductSelectionRule(
            NSE_EQUITY,
            ProductCode(default),
            frozenset(ProductCode(product) for product in supported),
        )
    return ProductSelectionPolicy(
        market_pack_id="india-equity",
        rule_version="india-products-v1",
        rules=(rule,),
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


def test_rule_requires_a_default_or_supported_products() -> None:
    with pytest.raises(ValueError, match="requires a default product or supported products"):
        ProductSelectionRule(NSE_EQUITY)


def test_rule_supported_products_must_be_a_frozenset() -> None:
    with pytest.raises(ValueError, match="must be a frozenset"):
        ProductSelectionRule(
            NSE_EQUITY,
            ProductCode("CNC"),
            {ProductCode("CNC")},  # type: ignore[arg-type]
        )


def test_rule_default_must_be_supported() -> None:
    with pytest.raises(ValueError, match="default product must be one of the supported"):
        ProductSelectionRule(
            NSE_EQUITY,
            ProductCode("CNC"),
            frozenset({ProductCode("MIS")}),
        )


def test_default_only_rule_supports_exactly_its_default() -> None:
    rule = ProductSelectionRule(NSE_EQUITY, ProductCode("CNC"))

    assert rule.effective_supported_products == frozenset({ProductCode("CNC")})
    assert rule.supports(ProductCode("CNC"))
    assert not rule.supports(ProductCode("MIS"))


def test_omitted_product_resolves_and_binds_pack_identity() -> None:
    result = resolve_request_product(_context(), explicit_product=None, policy=_policy())

    assert result.product == ProductCode("CNC")
    assert result.context.market_pack_id == "india-equity"
    assert result.context.rule_version == "india-products-v1"
    assert result.resolution is not None
    assert result.resolution.product == ProductCode("CNC")
    assert result.resolution.market == NSE_EQUITY
    assert result.resolution.market_pack_id == "india-equity"
    assert result.resolution.rule_version == "india-products-v1"
    assert result.resolution.supported_products == frozenset({ProductCode("CNC")})


def test_omitted_product_without_policy_stays_absent_for_simulated_modes() -> None:
    result = resolve_request_product(
        _context(mode=ExecutionMode.BACKTEST), explicit_product=None, policy=None
    )

    assert result.product is None
    assert result.context == _context(mode=ExecutionMode.BACKTEST)
    assert result.resolution is None


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


def test_explicit_supported_product_is_preserved_verbatim() -> None:
    context = _context(market_pack_id="india-equity", rule_version="india-products-v1")
    result = resolve_request_product(
        context,
        explicit_product=ProductCode("MIS"),
        policy=_policy(default="CNC", supported=("CNC", "MIS")),
    )

    assert result.product == ProductCode("MIS")
    assert result.context == context
    assert result.resolution is not None
    assert result.resolution.product == ProductCode("MIS")
    assert result.resolution.supported_products == frozenset(
        {ProductCode("CNC"), ProductCode("MIS")}
    )


def test_explicit_product_requires_a_supporting_policy() -> None:
    with pytest.raises(ProductSelectionError, match="requires a versioned market-pack"):
        resolve_request_product(_context(), explicit_product=ProductCode("MIS"), policy=None)


def test_explicit_product_forwarded_identity_does_not_replace_the_policy() -> None:
    with pytest.raises(ProductSelectionError, match="requires a versioned market-pack"):
        resolve_request_product(
            _context(market_pack_id="india-equity", rule_version="india-products-v1"),
            explicit_product=ProductCode("MIS"),
            policy=None,
        )


def test_explicit_product_must_be_supported_by_its_market_rule() -> None:
    with pytest.raises(ProductSelectionError, match="is not supported for market"):
        resolve_request_product(
            _context(),
            explicit_product=ProductCode("MIS"),
            policy=_policy(default="CNC"),
        )


def test_explicit_product_binds_the_policy_identity() -> None:
    result = resolve_request_product(
        _context(),
        explicit_product=ProductCode("MIS"),
        policy=_policy(default="CNC", supported=("CNC", "MIS")),
    )

    assert result.product == ProductCode("MIS")
    assert result.context.market_pack_id == "india-equity"
    assert result.context.rule_version == "india-products-v1"
    assert result.resolution is not None
    assert result.resolution.market_pack_id == "india-equity"
    assert result.resolution.rule_version == "india-products-v1"


def test_explicit_product_conflicting_policy_identity_is_rejected() -> None:
    with pytest.raises(ProductSelectionError, match="market-pack id conflicts"):
        resolve_request_product(
            _context(market_pack_id="other-pack"),
            explicit_product=ProductCode("MIS"),
            policy=_policy(default="CNC", supported=("CNC", "MIS")),
        )
    with pytest.raises(ProductSelectionError, match="rule version conflicts"):
        resolve_request_product(
            _context(rule_version="other-version"),
            explicit_product=ProductCode("MIS"),
            policy=_policy(default="CNC", supported=("CNC", "MIS")),
        )


def test_explicit_product_type_is_strict() -> None:
    with pytest.raises(ProductSelectionError, match="explicit product must be a ProductCode"):
        resolve_request_product(
            _context(),
            explicit_product="MIS",  # type: ignore[arg-type]
            policy=_policy(),
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
    result = resolve_request_product(context, explicit_product=None, policy=_policy())

    assert result.product == ProductCode("CNC")
    assert result.context == context
    assert result.resolution is not None


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
