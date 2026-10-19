"""QX-04: neutral product codes are interpreted by the India market pack."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode
from quantx.india.domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    ProductType,
)
from quantx.india.execution_rules import IndiaExecutionRuleEngine, IndiaRuleDecision
from quantx.india.product_selection import india_product_type, india_request_product
from quantx.india.rule_data import IndiaRuleScope, IndiaVenueRuleSnapshot

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


def _spec() -> IndianInstrumentSpec:
    return IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )


def _order() -> Order:
    return Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
    )


def _request(product: ProductCode | None) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("p-1"),
        deployment_id=StrategyDeploymentId("d-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id="india",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        product=product,
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        product=product,
        position_effect=PositionEffect.OPEN,
    )


@pytest.mark.parametrize("product", list(ProductType))
def test_india_product_code_preserves_pack_vocabulary(product: ProductType) -> None:
    assert india_product_type(ProductCode(f" {product.value.lower()} ")) is product


def test_unknown_product_code_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported India product code"):
        india_product_type(ProductCode("INTRADAY"))


def test_absent_product_is_not_a_default() -> None:
    assert india_request_product(_request(None)) is None
    assert india_request_product(_request(ProductCode("CNC"))) is ProductType.CNC


def test_neutral_product_feeds_india_asset_matrix() -> None:
    engine = IndiaExecutionRuleEngine()
    order = _order()

    allowed = engine.validate(_spec(), order, product=india_product_type(ProductCode("CNC")))
    rejected = engine.validate(_spec(), order, product=india_product_type(ProductCode("NRML")))

    assert allowed.decision is IndiaRuleDecision.APPROVE
    assert rejected.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRODUCT_INVALID" in rejected.reason


def test_neutral_product_feeds_versioned_venue_snapshot() -> None:
    snapshot = IndiaVenueRuleSnapshot(
        version="nse-eq-2026-01",
        provenance="nse-fixture",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        scope=IndiaRuleScope(
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
        ),
        allowed_products=frozenset({ProductType.CNC}),
    )
    result = IndiaExecutionRuleEngine().validate_compatibility(
        _spec(),
        _order(),
        product=india_product_type(ProductCode("MIS")),
        venue_rules=snapshot,
        evaluated_at=NOW,
    )

    assert result.decision is IndiaRuleDecision.REJECT
    assert result.rule_set_version == "nse-eq-2026-01"
    assert "INDIA_PRODUCT_INVALID: product MIS is not permitted" in result.reason
