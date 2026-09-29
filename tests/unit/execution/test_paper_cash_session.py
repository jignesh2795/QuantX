from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import Money
from quantx.execution.paper_engine import PaperExecutionEngine, QuoteSnapshot
from quantx.execution.paper_session import PaperSession
from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer
from quantx.execution.post_trade_risk import PostTradeRiskLimits
from quantx.execution.trading_gate import TradingGate


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


def _request(instrument: Instrument, side: OrderSide) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=side,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
    )


def test_stateful_paper_session_carries_cash_between_fills() -> None:
    instrument = _instrument()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        initial_cash=Money(Decimal("5000"), "INR"),
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    first = session.execute_and_value(_request(instrument, OrderSide.BUY), snapshot=snapshot)
    assert first.cash.amount == Decimal("4000")
    assert first.valuation.snapshot.cash.amount == Decimal("4000")
    assert first.financial_state is not None
    assert first.financial_state.state.cash_balance.amount == Decimal("4000")
    assert first.financial_state.state.available_cash.amount == Decimal("4000")
    assert first.financial_state.gross_exposure.amount == Decimal("1000")

    second = session.execute_and_value(_request(instrument, OrderSide.SELL), snapshot=snapshot)
    assert second.cash.amount == Decimal("5000")
    assert second.accounting_entry.quantity == Decimal("0")
    assert second.valuation.snapshot.cash.amount == Decimal("5000")
    assert second.financial_state is not None
    assert second.financial_state.state.cash_balance.amount == Decimal("5000")
    assert second.financial_state.gross_exposure.amount == Decimal("0")


def test_stateful_paper_session_applies_fees_to_cash_once() -> None:
    from quantx.execution.paper_engine import PaperSimulationProfile

    instrument = _instrument()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        profile=PaperSimulationProfile(fee_bps=Decimal("10")),
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        initial_cash=Money(Decimal("5000"), "INR"),
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    result = session.execute_and_value(_request(instrument, OrderSide.BUY), snapshot=snapshot)

    assert result.execution.fee == Decimal("1.00")
    assert result.cash.amount == Decimal("3999")
    assert result.cash_entries[0].fee.amount == Decimal("1.00")


def test_paper_session_feeds_account_snapshot_to_post_trade_risk() -> None:
    instrument = _instrument()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    gate = TradingGate()
    risk = PostTradeRiskEnforcer(
        limits=PostTradeRiskLimits(max_exposure=Money(Decimal("500"), "INR")),
        trading_gate=gate,
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        initial_cash=Money(Decimal("5000"), "INR"),
        post_trade_risk=risk,
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    result = session.execute_and_value(
        _request(instrument, OrderSide.BUY),
        snapshot=snapshot,
    )

    assert result.financial_state is not None
    assert result.financial_state.gross_exposure.amount == Decimal("1000")
    assert result.risk_enforcement is not None
    assert result.risk_enforcement.breached
    assert not gate.allow()
