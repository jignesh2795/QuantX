from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.risk import RiskDecision, RiskResult


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
        instrument=__import__("quantx.domain.value_objects", fromlist=["InstrumentId"]).InstrumentId("NSE", "TCS"),
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
        instrument=__import__("quantx.domain.value_objects", fromlist=["InstrumentId"]).InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=__import__("quantx.domain.enums", fromlist=["OrderType"]).OrderType.MARKET,
        quantity=Decimal("1"),
    )
    approved = RiskResult(RiskDecision.APPROVE, "approved")
    with pytest.raises(ValueError, match="broker connection"):
        ApprovedExecutionRequest(order, _context(ExecutionMode.LIVE), approved)
