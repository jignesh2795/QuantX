from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.paper import PaperExecutionEngine, PaperExecutionError, PaperSimulationProfile, QuoteSnapshot


def _request(mode: ExecutionMode = ExecutionMode.PAPER) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("paper-1") if mode is ExecutionMode.LIVE else None,
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    order = __import__("quantx.domain.execution_request", fromlist=["build_order_from_intent"]).build_order_from_intent(intent)
    return ApprovedExecutionRequest(order, context, RiskResult(RiskDecision.APPROVE, "approved"))


def test_market_buy_uses_ask_and_explicit_slippage() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        profile=PaperSimulationProfile(slippage_bps=Decimal("10")),
    )
    receipt = engine.execute(
        _request(),
        quote=QuoteSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            bid=Decimal("99"),
            ask=Decimal("100"),
        ),
    )
    assert receipt.simulated is True
    assert receipt.fills[0].price == Decimal("100.10")


def test_repeated_client_order_is_idempotent() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    request = _request()
    quote = QuoteSnapshot(datetime(2026, 1, 1, tzinfo=timezone.utc), last=Decimal("100"))
    first = engine.execute(request, quote=quote)
    second = engine.execute(request, quote=quote)
    assert first == second
    assert len(engine.events()) == 2


def test_missing_required_price_is_not_invented() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    with pytest.raises(PaperExecutionError, match="price"):
        engine.execute(
            _request(),
            quote=QuoteSnapshot(datetime(2026, 1, 1, tzinfo=timezone.utc), bid=Decimal("99")),
        )


def test_paper_engine_rejects_live_mode() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    with pytest.raises(PaperExecutionError, match="PAPER, SHADOW, or REPLAY"):
        engine.execute(
            _request(ExecutionMode.LIVE),
            quote=QuoteSnapshot(datetime(2026, 1, 1, tzinfo=timezone.utc), last=Decimal("100")),
        )
