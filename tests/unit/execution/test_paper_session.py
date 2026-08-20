from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import Money
from quantx.execution.paper import PaperExecutionEngine, QuoteSnapshot
from quantx.execution.paper_session import PaperSession


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=market,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _request() -> ApprovedExecutionRequest:
    market = _instrument().market
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=_instrument().instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    from quantx.domain.execution_request import build_order_from_intent

    order = build_order_from_intent(intent)
    return ApprovedExecutionRequest(order, context, RiskResult(RiskDecision.APPROVE, "approved"))


def test_execute_account_and_value_uses_observed_mark() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    session = PaperSession(executor=engine)
    result = session.execute_and_value(
        _request(),
        instrument=_instrument(),
        quote=QuoteSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
        cash=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
    )
    assert result.accounting_entry.quantity == Decimal("10")
    assert result.valuation.completeness == "COMPLETE"
    assert result.valuation.snapshot.unrealized_pnl.amount == Decimal("0")


def test_missing_mark_produces_incomplete_valuation() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    session = PaperSession(executor=engine)
    result = session.execute_and_value(
        _request(),
        instrument=_instrument(),
        quote=QuoteSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ask=Decimal("100"),
        ),
        cash=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
    )
    assert result.valuation.completeness == "INCOMPLETE"
    assert result.valuation.unavailable_instruments
