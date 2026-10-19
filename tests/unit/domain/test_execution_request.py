from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode


def _context(mode: ExecutionMode, connection_id=None) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=connection_id,
        execution_mode=mode,
    )


def test_order_is_derived_from_intent() -> None:
    intent = TradeIntent(
        instrument=__import__(
            "quantx.domain.value_objects", fromlist=["InstrumentId"]
        ).InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=_context(ExecutionMode.PAPER),
    )
    order = build_order_from_intent(intent)
    assert isinstance(order, Order)
    assert order.instrument == intent.instrument
    assert order.quantity == intent.quantity


def test_live_execution_requires_broker_connection() -> None:
    order = Order(
        instrument=__import__(
            "quantx.domain.value_objects", fromlist=["InstrumentId"]
        ).InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=__import__("quantx.domain.enums", fromlist=["OrderType"]).OrderType.MARKET,
        quantity=Decimal("1"),
    )
    approved = RiskResult(RiskDecision.APPROVE, "approved")
    with pytest.raises(ValueError, match="broker connection"):
        ApprovedExecutionRequest(order, _context(ExecutionMode.LIVE), approved)


def test_build_order_from_intent_preserves_product_and_position_effect() -> None:
    context = _context(ExecutionMode.PAPER)
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        product=ProductCode("INTRADAY"),
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    assert order.product == ProductCode("INTRADAY")
    assert order.position_effect is PositionEffect.OPEN


def _paper_request(
    order: Order,
    *,
    position_effect: PositionEffect | None = None,
    effective_position_effect: PositionEffect | None = None,
) -> ApprovedExecutionRequest:
    return ApprovedExecutionRequest(
        order=order,
        execution_context=_context(ExecutionMode.PAPER),
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        product=order.product,
        position_effect=position_effect,
        effective_position_effect=effective_position_effect,
    )


def test_auto_position_effect_requires_resolved_effective_effect() -> None:
    order = build_order_from_intent(
        TradeIntent(
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            position_effect=PositionEffect.AUTO,
            execution_context=_context(ExecutionMode.PAPER),
        )
    )
    with pytest.raises(ValueError, match="AUTO position effect requires"):
        _paper_request(order, position_effect=PositionEffect.AUTO)


def test_auto_position_effect_rejects_unresolved_effective_value() -> None:
    order = build_order_from_intent(
        TradeIntent(
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            execution_context=_context(ExecutionMode.PAPER),
        )
    )
    with pytest.raises(ValueError, match="resolved AUTO effect"):
        _paper_request(
            order,
            position_effect=PositionEffect.AUTO,
            effective_position_effect=PositionEffect.AUTO,
        )


@pytest.mark.parametrize("effective", [PositionEffect.OPEN, PositionEffect.CLOSE])
def test_auto_position_effect_accepts_resolved_open_or_close(
    effective: PositionEffect,
) -> None:
    order = build_order_from_intent(
        TradeIntent(
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            execution_context=_context(ExecutionMode.PAPER),
        )
    )
    request = _paper_request(
        order,
        position_effect=PositionEffect.AUTO,
        effective_position_effect=effective,
    )
    assert request.position_effect is PositionEffect.AUTO
    assert request.effective_position_effect is effective


def test_explicit_position_effect_and_product_are_preserved() -> None:
    order = build_order_from_intent(
        TradeIntent(
            instrument=InstrumentId("NSE", "TCS"),
            side=OrderSide.SELL,
            quantity=Decimal("10"),
            product=ProductCode("CNC"),
            position_effect=PositionEffect.CLOSE,
            execution_context=_context(ExecutionMode.PAPER),
        )
    )
    request = _paper_request(order, position_effect=PositionEffect.CLOSE)
    assert request.product == ProductCode("CNC")
    assert request.position_effect is PositionEffect.CLOSE
