"""Focused tests for canonical request fingerprinting."""

from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.idempotency.fingerprint import _canonical_decimal, request_fingerprint


def _request(
    *,
    quantity: Decimal = Decimal("10"),
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    return ApprovedExecutionRequest(
        order, context, RiskResult(RiskDecision.APPROVE, "approved"), None
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
