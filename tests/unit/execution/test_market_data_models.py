from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.orders import Order
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.models import QuoteFillModel, SlippageModel


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("paper-1"),
        execution_mode=ExecutionMode.PAPER,
    )


def _request(side: OrderSide) -> ApprovedExecutionRequest:
    order = Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    return ApprovedExecutionRequest(order, _context(), RiskResult(RiskDecision.APPROVE, "ok"))


def test_market_snapshot_does_not_invent_missing_quote() -> None:
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime.now(timezone.utc),
        last=Decimal("100"),
    )
    assert snapshot.mid is None
    assert snapshot.spread is None
    assert QuoteFillModel().propose_fill(_request(OrderSide.BUY), snapshot) is None


def test_market_buy_uses_observed_ask() -> None:
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime.now(timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
    )
    proposal = QuoteFillModel().propose_fill(_request(OrderSide.BUY), snapshot)
    assert proposal is not None
    assert proposal.price == Decimal("100")


def test_slippage_moves_fill_against_trader() -> None:
    model = SlippageModel(Decimal("10"))
    assert model.apply(OrderSide.BUY, Decimal("100")) == Decimal("100.1")
    assert model.apply(OrderSide.SELL, Decimal("100")) == Decimal("99.90009990009990009990009990")
