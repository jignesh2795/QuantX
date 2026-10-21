from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, PositionEffect
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.instruments import (
    Contract,
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision
from quantx.domain.value_objects import Money


def _context() -> RiskContext:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
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


def _option_instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "NIFTY26JAN25000CE"),
        "NIFTY26JAN25000CE",
        AssetClass.OPTION,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("25"),
    )


def _option_contract(**overrides) -> Contract:
    values = dict(
        instrument_id=_option_instrument().instrument_id,
        asset_class=AssetClass.OPTION,
        underlying=InstrumentId("NSE", "NIFTY"),
        expiry=datetime(2026, 1, 29, 15, 30, tzinfo=UTC),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
    )
    values.update(overrides)
    return Contract(**values)


def _option_context(contract: Contract | None = None) -> RiskContext:
    base = _context()
    return RiskContext(
        _option_instrument(),
        base.financial_state,
        reference_price=Decimal("100"),
        contract=contract,
    )


def _option_intent() -> TradeIntent:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    return TradeIntent(
        instrument=_option_instrument().instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        required_margin=Decimal("1000"),
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )


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


def test_absent_effect_resolved_to_open_requires_pack_identity() -> None:
    context = replace(_context(), effective_position_effect=PositionEffect.OPEN)

    result = PreTradeRiskEngine().evaluate(_intent(), context)

    assert result.decision is RiskDecision.REJECT
    assert "requires a market-pack id" in result.reason


def test_absent_effect_resolved_to_open_with_identity_is_accepted() -> None:
    context = replace(
        _context(),
        effective_position_effect=PositionEffect.OPEN,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )

    result = PreTradeRiskEngine().evaluate(_intent(), context)

    assert result.decision is RiskDecision.APPROVE


def test_absent_effect_cannot_resolve_to_close() -> None:
    context = replace(
        _context(),
        effective_position_effect=PositionEffect.CLOSE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )

    result = PreTradeRiskEngine().evaluate(_intent(), context)

    assert result.decision is RiskDecision.REJECT
    assert "may only resolve to OPEN" in result.reason


def test_explicit_open_cannot_carry_a_resolved_effect() -> None:
    context = replace(
        _context(),
        effective_position_effect=PositionEffect.OPEN,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )

    result = PreTradeRiskEngine().evaluate(_intent(position_effect=PositionEffect.OPEN), context)

    assert result.decision is RiskDecision.REJECT
    assert "explicit OPEN request cannot carry" in result.reason


def test_derivative_risk_requires_resolved_contract_metadata() -> None:
    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context())

    assert result.decision is RiskDecision.REJECT
    assert "derivative instrument requires resolved contract metadata" in result.reason


def test_derivative_risk_accepts_matching_contract_metadata() -> None:
    contract = _option_contract()

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(contract))

    assert result.decision is RiskDecision.APPROVE


def test_derivative_risk_rejects_contract_for_another_instrument() -> None:
    foreign = _option_contract(instrument_id=InstrumentId("NSE", "NIFTY26JAN26000CE"))

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(foreign))

    assert result.decision is RiskDecision.REJECT
    assert "resolved contract instrument does not match" in result.reason


def test_non_derivative_risk_rejects_contract_metadata() -> None:
    result = PreTradeRiskEngine().evaluate(
        _intent(),
        replace(_context(), contract=_option_contract()),
    )

    assert result.decision is RiskDecision.REJECT
    assert "non-derivative instrument cannot carry contract metadata" in result.reason


def test_risk_rejects_a_context_instrument_that_does_not_match_the_intent() -> None:
    result = PreTradeRiskEngine().evaluate(
        _intent(instrument=InstrumentId("NSE", "INFY")),
        _context(),
    )

    assert result.decision is RiskDecision.REJECT
    assert "risk context instrument does not match" in result.reason


def test_derivative_intent_cannot_borrow_an_equity_context() -> None:
    result = PreTradeRiskEngine().evaluate(_option_intent(), _context())

    assert result.decision is RiskDecision.REJECT
    assert "risk context instrument does not match" in result.reason
