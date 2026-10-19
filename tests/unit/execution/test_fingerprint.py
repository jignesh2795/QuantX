"""Focused tests for canonical request fingerprinting."""

from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode
from quantx.execution.idempotency.fingerprint import _canonical_decimal, request_fingerprint


def _request(
    *,
    quantity: Decimal = Decimal("10"),
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    product: ProductCode | None = None,
    position_effect: PositionEffect | None = None,
    effective_position_effect: PositionEffect | None = None,
    market_pack_id: str | None = None,
    rule_version: str | None = None,
) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        product=product,
        position_effect=position_effect,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    return ApprovedExecutionRequest(
        order,
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        None,
        product=product,
        position_effect=position_effect,
        effective_position_effect=effective_position_effect,
    )


def test_equivalent_quantities_share_fingerprint() -> None:
    first = request_fingerprint(_request(quantity=Decimal("10")))
    second = request_fingerprint(_request(quantity=Decimal("10.0")))
    third = request_fingerprint(_request(quantity=Decimal("10.00")))
    assert first == second == third


def test_different_quantities_have_different_fingerprints() -> None:
    assert request_fingerprint(_request(quantity=Decimal("10"))) != request_fingerprint(
        _request(quantity=Decimal("11"))
    )


def test_equivalent_limit_prices_share_fingerprint() -> None:
    first = request_fingerprint(_request(order_type=OrderType.LIMIT, limit_price=Decimal("100")))
    second = request_fingerprint(_request(order_type=OrderType.LIMIT, limit_price=Decimal("100.0")))
    assert first == second


def test_equivalent_stop_prices_share_fingerprint() -> None:
    first = request_fingerprint(_request(order_type=OrderType.STOP, stop_price=Decimal("99.5")))
    second = request_fingerprint(_request(order_type=OrderType.STOP, stop_price=Decimal("99.50")))
    assert first == second


def test_non_finite_decimals_are_deterministic() -> None:
    assert _canonical_decimal(Decimal("NaN")) == _canonical_decimal(Decimal("NaN"))
    assert _canonical_decimal(Decimal("Infinity")) == _canonical_decimal(Decimal("Infinity"))
    assert _canonical_decimal(Decimal("-Infinity")) == _canonical_decimal(Decimal("-Infinity"))


def test_fingerprint_is_stable() -> None:
    assert request_fingerprint(_request()) == request_fingerprint(_request())


def test_identity_fields_are_excluded_from_fingerprint() -> None:
    first_request = _request()
    second_request = _request()
    assert first_request.order.client_order_id != second_request.order.client_order_id
    assert request_fingerprint(first_request) == request_fingerprint(second_request)


def test_different_products_have_different_fingerprints() -> None:
    assert request_fingerprint(_request(product=ProductCode("CNC"))) != request_fingerprint(
        _request(product=ProductCode("INTRADAY"))
    )


def test_same_product_has_stable_fingerprint() -> None:
    assert request_fingerprint(_request(product=ProductCode("CNC"))) == request_fingerprint(
        _request(product=ProductCode("CNC"))
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (None, PositionEffect.OPEN),
        (PositionEffect.OPEN, PositionEffect.CLOSE),
        (PositionEffect.OPEN, PositionEffect.AUTO),
    ],
)
def test_different_requested_effects_have_different_fingerprints(
    first: PositionEffect | None,
    second: PositionEffect | None,
) -> None:
    first_request = _request(
        position_effect=first,
        effective_position_effect=PositionEffect.OPEN if first is PositionEffect.AUTO else None,
    )
    second_request = _request(
        position_effect=second,
        effective_position_effect=PositionEffect.OPEN if second is PositionEffect.AUTO else None,
    )
    assert request_fingerprint(first_request) != request_fingerprint(second_request)


def test_different_resolved_auto_effects_have_different_fingerprints() -> None:
    open_request = _request(
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.OPEN,
    )
    close_request = _request(
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.CLOSE,
    )
    assert request_fingerprint(open_request) != request_fingerprint(close_request)


def test_rule_identity_changes_fingerprint() -> None:
    base = _request(product=ProductCode("CNC"), market_pack_id="india-equity", rule_version="v1")
    next_version = _request(
        product=ProductCode("CNC"), market_pack_id="india-equity", rule_version="v2"
    )
    other_pack = _request(product=ProductCode("CNC"), market_pack_id="india-fno", rule_version="v1")
    base_fingerprint = request_fingerprint(base)
    assert request_fingerprint(next_version) != base_fingerprint
    assert request_fingerprint(other_pack) != base_fingerprint
