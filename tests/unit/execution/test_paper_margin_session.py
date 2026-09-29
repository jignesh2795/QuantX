from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import Money
from quantx.execution.margin_ledger import MarginLedger
from quantx.execution.paper_engine import PaperExecutionEngine, QuoteSnapshot
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


def _request(instrument: Instrument, side: OrderSide, required_margin: Decimal = Decimal("0")) -> ApprovedExecutionRequest:
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
        required_margin=required_margin,
    )
    return ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        required_margin=required_margin,
    )


def _snapshot(instrument: Instrument) -> QuoteSnapshot:
    return QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )


def test_paper_session_tracks_margin_until_position_closes() -> None:
    instrument = _instrument()
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        initial_cash=Money(Decimal("5000"), "INR"),
        margin_ledger=MarginLedger(Decimal("5000")),
    )

    opened = session.execute_and_value(
        _request(instrument, OrderSide.BUY, Decimal("1500")),
        snapshot=_snapshot(instrument),
    )
    assert opened.margin_used is not None
    assert opened.margin_used.amount == Decimal("1500")
    assert opened.valuation.snapshot.margin_used.amount == Decimal("1500")

    closed = session.execute_and_value(
        _request(instrument, OrderSide.SELL),
        snapshot=_snapshot(instrument),
    )
    assert closed.margin_used is not None
    assert closed.margin_used.amount == Decimal("0")
    assert closed.valuation.snapshot.margin_used.amount == Decimal("0")
