from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType, BrokerConstraint
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision
from quantx.domain.value_objects import Money


def _context() -> RiskContext:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    instrument = Instrument(
        InstrumentId("NSE", "TCS"), "TCS", AssetClass.EQUITY, market, "INR", Decimal("0.05"), Decimal("1")
    )
    financial = AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )
    return RiskContext(instrument, financial, reference_price=Decimal("100"))


def _intent(**overrides) -> TradeIntent:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    values = dict(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        required_margin=Decimal("1000"),
        execution_context=context,
    )
    values.update(overrides)
    return TradeIntent(**values)


def test_pre_trade_risk_approves_valid_intent() -> None:
    result = PreTradeRiskEngine().evaluate(_intent(), _context())
    assert result.decision == RiskDecision.APPROVE


def test_pre_trade_risk_rejects_insufficient_margin() -> None:
    result = PreTradeRiskEngine().evaluate(
        _intent(required_margin=Decimal("200000")),
        _context(),
    )
    assert result.decision == RiskDecision.REJECT


def test_pre_trade_risk_requires_explicit_approval() -> None:
    result = PreTradeRiskEngine().evaluate(
        _intent(approval_required=True),
        _context(),
    )
    assert result.decision == RiskDecision.APPROVAL_REQUIRED


def test_pre_trade_risk_enforces_broker_minimum() -> None:
    context = _context()
    context = RiskContext(
        context.instrument,
        context.financial_state,
        broker_constraints=(
            BrokerConstraint("min-value", "broker minimum", minimum_order_value=Decimal("5000")),
        ),
        reference_price=Decimal("100"),
    )
    result = PreTradeRiskEngine().evaluate(_intent(quantity=Decimal("10")), context)
    assert result.decision == RiskDecision.REJECT
