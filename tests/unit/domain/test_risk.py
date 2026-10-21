from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, PositionEffect
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.instrument_registry import InstrumentResolution
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
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision, RiskResult
from quantx.domain.value_objects import Money

RULE_FROM = datetime(2026, 1, 1, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


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


def _equity_instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _option_resolution(
    *,
    contract: Contract | None = None,
    instrument: Instrument | None = None,
    metadata_version: str = "contract-v1",
    rule_version: str = "rule-v1",
    rule_from: datetime = RULE_FROM,
    resolved_at: datetime = RESOLVED_AT,
) -> InstrumentResolution:
    return InstrumentResolution(
        instrument=instrument or _option_instrument(),
        contract=_option_contract() if contract is None else contract,
        instrument_rule_version=rule_version,
        instrument_rule_effective_from=rule_from,
        resolved_at=resolved_at,
        contract_metadata_version=metadata_version,
        contract_source="nse-bhavcopy",
        contract_effective_from=RULE_FROM,
    )


def _equity_resolution() -> InstrumentResolution:
    return InstrumentResolution(
        instrument=_equity_instrument(),
        instrument_rule_version="rule-v1",
        instrument_rule_effective_from=RULE_FROM,
        resolved_at=RESOLVED_AT,
    )


def _option_context(resolution: InstrumentResolution | None = None) -> RiskContext:
    base = _context()
    return RiskContext(
        _option_instrument(),
        base.financial_state,
        reference_price=Decimal("100"),
        instrument_resolution=resolution,
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


def test_derivative_risk_requires_a_resolved_instrument_resolution() -> None:
    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context())

    assert result.decision is RiskDecision.REJECT
    assert "derivative instrument requires a resolved instrument resolution" in result.reason


def test_derivative_risk_accepts_the_matching_canonical_resolution() -> None:
    resolution = _option_resolution()

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(resolution))

    assert result.decision is RiskDecision.APPROVE
    assert result.instrument_resolution is resolution


def test_derivative_risk_result_retains_the_selected_identity_not_just_the_contract() -> None:
    resolution = _option_resolution(metadata_version="contract-v7", rule_version="rule-v9")

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(resolution))

    assert result.decision is RiskDecision.APPROVE
    carried = result.instrument_resolution
    assert carried is resolution
    assert carried is not None
    # The identity risk approved is the versioned claim, not an equal Contract.
    assert carried.contract == resolution.contract
    assert carried.contract_metadata_version == "contract-v7"
    assert carried.contract_source == "nse-bhavcopy"
    assert carried.contract_effective_from == RULE_FROM
    assert carried.instrument_rule_version == "rule-v9"
    assert carried.instrument_rule_effective_from == RULE_FROM


def test_derivative_risk_rejects_a_resolution_for_another_instrument() -> None:
    result = PreTradeRiskEngine().evaluate(
        _option_intent(),
        _option_context(_equity_resolution()),
    )

    assert result.decision is RiskDecision.REJECT
    assert "resolved instrument does not match the intent instrument" in result.reason


def test_derivative_risk_rejects_an_instrument_identity_contradiction() -> None:
    # Same InstrumentId, different canonical instrument facts: the resolution
    # cannot silently substitute a different tick/lot/multiplier for risk.
    contradicted = replace(_option_instrument(), lot_size=Decimal("50"))
    resolution = replace(_option_resolution(), instrument=contradicted)

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(resolution))

    assert result.decision is RiskDecision.REJECT
    assert "resolved instrument does not match the risk context instrument" in result.reason


def test_derivative_risk_rejects_a_tampered_contract_identity() -> None:
    # The canonical type makes this state unconstructible; risk still refuses
    # it if a malformed object is smuggled across the boundary.
    resolution = _option_resolution()
    object.__setattr__(
        resolution,
        "contract",
        _option_contract(instrument_id=InstrumentId("NSE", "NIFTY26JAN26000CE")),
    )

    result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(resolution))

    assert result.decision is RiskDecision.REJECT
    assert "resolved contract instrument does not match" in result.reason


def test_derivative_risk_rejects_a_tampered_metadata_version_or_provenance() -> None:
    for field, expected in (
        ("contract_metadata_version", "requires a contract metadata version"),
        ("contract_source", "requires contract metadata provenance"),
        ("contract_effective_from", "requires a contract effective instant"),
    ):
        resolution = _option_resolution()
        object.__setattr__(resolution, field, None)

        result = PreTradeRiskEngine().evaluate(_option_intent(), _option_context(resolution))

        assert result.decision is RiskDecision.REJECT
        assert expected in result.reason


def test_non_derivative_risk_rejects_tampered_contract_metadata() -> None:
    resolution = _equity_resolution()
    object.__setattr__(resolution, "contract", _option_contract())
    object.__setattr__(resolution, "contract_metadata_version", "contract-v1")
    object.__setattr__(resolution, "contract_source", "nse-bhavcopy")
    object.__setattr__(resolution, "contract_effective_from", RULE_FROM)

    result = PreTradeRiskEngine().evaluate(
        _intent(), replace(_context(), instrument_resolution=resolution)
    )

    assert result.decision is RiskDecision.REJECT
    assert "non-derivative instrument cannot carry contract metadata" in result.reason


def test_non_derivative_risk_restates_the_legacy_contract_without_a_resolution() -> None:
    result = PreTradeRiskEngine().evaluate(_intent(), _context())

    assert result.decision is RiskDecision.APPROVE
    assert result.instrument_resolution is None
    assert _context().contract is None


def test_non_derivative_risk_carries_a_compatible_resolution_without_a_contract() -> None:
    resolution = _equity_resolution()
    context = replace(_context(), instrument_resolution=resolution)

    result = PreTradeRiskEngine().evaluate(_intent(), context)

    assert result.decision is RiskDecision.APPROVE
    assert result.instrument_resolution is resolution
    assert context.contract is None


def test_risk_result_rejects_a_non_canonical_resolution() -> None:
    with pytest.raises(ValueError, match="canonical instrument resolution"):
        RiskResult(
            RiskDecision.APPROVE,
            "approved",
            instrument_resolution=object(),  # type: ignore[arg-type]
        )


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
