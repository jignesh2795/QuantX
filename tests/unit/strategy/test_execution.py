from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, PositionEffect
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext
from quantx.domain.position_effect import PositionEvidence
from quantx.domain.product_selection import (
    ProductSelectionError,
    ProductSelectionPolicy,
    ProductSelectionRule,
)
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskResult
from quantx.domain.strategy import (
    SignalAction,
    StrategyId,
    StrategyResult,
    StrategySignal,
)
from quantx.domain.value_objects import Money, ProductCode
from quantx.india.market_pack import (
    INDIA_EQUITY_POSITION_EFFECT_POLICY,
    INDIA_EQUITY_PRODUCT_SELECTION,
)
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.execution import StrategyExecutionPreparer


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _event() -> MarketDataEvent:
    instrument = InstrumentId("NSE", "TCS")
    timestamp = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("99"), ask=Decimal("100"), last=Decimal("100")),
    )


def _deployment() -> StrategyDeployment:
    return StrategyDeployment(
        deployment_id=StrategyDeploymentId("deploy-1"),
        strategy_id="buy-and-hold",
        strategy_version="1",
        portfolio_id=PortfolioId("portfolio-1"),
        account_id=AccountId("acct-1"),
        market=_market(),
        execution_mode=ExecutionMode.PAPER,
        enabled=True,
    )


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _decision(
    *,
    quantity: Decimal = Decimal("10"),
    required_margin: Decimal = Decimal("1000"),
    required_capabilities: frozenset[str] = frozenset(),
    side: OrderSide = OrderSide.BUY,
    product: ProductCode | None = None,
    position_effect: PositionEffect | None = None,
    context: ExecutionContext | None = None,
) -> StrategyExecutionDecision:
    event = _event()
    signal = StrategySignal(
        strategy_id=StrategyId("buy-and-hold"),
        strategy_version="1",
        instrument=event.instrument,
        action=SignalAction.BUY if side is OrderSide.BUY else SignalAction.SELL,
        confidence=1.0,
        generated_at=event.timestamp,
    )
    intent = TradeIntent(
        instrument=event.instrument,
        side=side,
        quantity=quantity,
        required_margin=required_margin,
        required_capabilities=required_capabilities,
        strategy_id="buy-and-hold",
        strategy_version="1",
        product=product,
        position_effect=position_effect,
        execution_context=context or _execution_context(),
    )
    return StrategyExecutionDecision(
        deployment=_deployment(),
        result=StrategyResult(signal=signal, intent=intent),
    )


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _preparer(
    *,
    risk_engine=None,
    policy_engine=None,
    product_selection=None,
) -> StrategyExecutionPreparer:
    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
    return StrategyExecutionPreparer(
        InMemoryInstrumentRegistry((instrument,)),
        risk_engine=risk_engine,
        policy_engine=policy_engine,
        product_selection=product_selection,
        position_effect_policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
    )


def test_preparer_rejects_disabled_deployment() -> None:
    deployment = _deployment()
    disabled = StrategyDeployment(
        deployment_id=deployment.deployment_id,
        strategy_id=deployment.strategy_id,
        strategy_version=deployment.strategy_version,
        portfolio_id=deployment.portfolio_id,
        account_id=deployment.account_id,
        market=deployment.market,
        execution_mode=deployment.execution_mode,
        enabled=False,
    )
    decision = StrategyExecutionDecision(disabled, _decision().result)

    with pytest.raises(ValueError, match="disabled"):
        _preparer().prepare(decision, _event(), _financial_state())


def test_preparer_rejects_deployment_strategy_identity_mismatch() -> None:
    deployment = _deployment()
    mismatched = StrategyDeployment(
        deployment_id=deployment.deployment_id,
        strategy_id="other-strategy",
        strategy_version=deployment.strategy_version,
        portfolio_id=deployment.portfolio_id,
        account_id=deployment.account_id,
        market=deployment.market,
        execution_mode=deployment.execution_mode,
        enabled=True,
    )
    decision = StrategyExecutionDecision(mismatched, _decision().result)

    with pytest.raises(ValueError, match="strategy id"):
        _preparer().prepare(decision, _event(), _financial_state())


def test_preparer_rejects_deployment_market_mismatch() -> None:
    deployment = _deployment()
    wrong_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    mismatched = StrategyDeployment(
        deployment_id=deployment.deployment_id,
        strategy_id=deployment.strategy_id,
        strategy_version=deployment.strategy_version,
        portfolio_id=deployment.portfolio_id,
        account_id=deployment.account_id,
        market=wrong_market,
        execution_mode=deployment.execution_mode,
        enabled=True,
    )
    decision = StrategyExecutionDecision(mismatched, _decision().result)

    with pytest.raises(ValueError, match="market venue"):
        _preparer().prepare(decision, _event(), _financial_state())


def test_preparer_builds_approved_execution_request() -> None:
    result = _preparer().prepare(_decision(), _event(), _financial_state())

    assert result.risk_result is not None
    assert result.risk_result.decision.value == "approve"
    assert result.policy_result is not None
    assert result.policy_result.approved
    assert result.request is not None
    assert result.request.order.instrument == _event().instrument
    assert result.request.order.quantity == Decimal("10")
    assert result.request.risk_result == result.risk_result


def test_preparer_stops_on_risk_rejection() -> None:
    result = _preparer().prepare(
        _decision(required_margin=Decimal("200000")),
        _event(),
        _financial_state(),
    )

    assert result.risk_result is not None
    assert result.risk_result.decision.value == "reject"
    assert result.policy_result is None
    assert result.request is None


def test_preparer_stops_on_policy_rejection() -> None:
    result = _preparer().prepare(
        _decision(required_capabilities=frozenset({"broker.write"})),
        _event(),
        _financial_state(),
    )

    assert result.risk_result is not None
    assert result.risk_result.decision.value == "approve"
    assert result.policy_result is not None
    assert not result.policy_result.approved
    assert result.request is None


def test_preparer_rejects_intent_deployment_mismatch() -> None:
    decision = _decision()
    bad_intent = TradeIntent(
        instrument=_event().instrument,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=ExecutionContext(
            account_id=AccountId("other"),
            portfolio_id=PortfolioId("portfolio-1"),
            deployment_id=StrategyDeploymentId("deploy-1"),
            market=_market(),
            broker_connection_id=None,
            execution_mode=ExecutionMode.PAPER,
        ),
        strategy_id="buy-and-hold",
        strategy_version="1",
    )
    decision = StrategyExecutionDecision(
        decision.deployment,
        StrategyResult(decision.result.signal, bad_intent),
    )

    with pytest.raises(ValueError, match="account"):
        _preparer().prepare(decision, _event(), _financial_state())


def test_preparer_rejects_intent_strategy_identity_mismatch() -> None:
    decision = _decision()
    bad_intent = TradeIntent(
        instrument=_event().instrument,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=_execution_context(),
        strategy_id="other-strategy",
        strategy_version="1",
    )
    decision = StrategyExecutionDecision(
        decision.deployment,
        StrategyResult(decision.result.signal, bad_intent),
    )

    with pytest.raises(ValueError, match="intent id"):
        _preparer().prepare(decision, _event(), _financial_state())


def test_preparer_rejects_missing_instrument_metadata() -> None:
    with pytest.raises(ValueError, match="instrument metadata"):
        StrategyExecutionPreparer(
            InMemoryInstrumentRegistry(),
            position_effect_policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
        ).prepare(
            _decision(),
            _event(),
            _financial_state(),
        )


def test_preparer_returns_no_request_for_non_executable_result() -> None:
    decision = _decision()
    hold = StrategyResult(
        StrategySignal(
            strategy_id=decision.result.signal.strategy_id,
            strategy_version="1",
            instrument=_event().instrument,
            action=SignalAction.HOLD,
            confidence=1.0,
            generated_at=_event().timestamp,
        )
    )
    result = _preparer().prepare(
        StrategyExecutionDecision(decision.deployment, hold),
        _event(),
        _financial_state(),
    )

    assert result.risk_result is None
    assert result.policy_result is None
    assert result.request is None


class _RecordingRiskEngine:
    """Spy risk engine: records exactly what was submitted for approval."""

    def __init__(self) -> None:
        self.intents: list[TradeIntent] = []
        self.contexts: list[RiskContext] = []

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskResult:
        self.intents.append(intent)
        self.contexts.append(context)
        return PreTradeRiskEngine().evaluate(intent, context)


class _RecordingPolicyEngine:
    def __init__(self) -> None:
        self.intents: list[TradeIntent] = []

    def evaluate(self, intent: TradeIntent, context: PolicyContext):
        self.intents.append(intent)
        return ExecutionPolicyEngine().evaluate(intent, context)


def _close_or_auto_evidence(quantity: str = "5") -> PositionEvidence:
    cut = _event().timestamp
    return PositionEvidence(
        instrument=_event().instrument,
        quantity=Decimal(quantity),
        observed_at=cut,
        evidence_cut=cut,
        matched=True,
    )


def test_preparer_resolves_omitted_product_before_risk_approval() -> None:
    risk = _RecordingRiskEngine()
    policy = _RecordingPolicyEngine()

    result = _preparer(
        risk_engine=risk,
        policy_engine=policy,
        product_selection=INDIA_EQUITY_PRODUCT_SELECTION,
    ).prepare(_decision(), _event(), _financial_state())

    assert result.request is not None
    assert len(risk.contexts) == 1
    assert risk.contexts[0].product == ProductCode("CNC")
    assert risk.contexts[0].market_pack_id == "india-equity"
    assert risk.contexts[0].rule_version == "india-products-v1"
    assert risk.intents[0].product == ProductCode("CNC")
    assert policy.intents[0].product == ProductCode("CNC")
    assert result.request.product == ProductCode("CNC")
    assert result.request.execution_context.market_pack_id == "india-equity"
    assert result.request.execution_context.rule_version == "india-products-v1"


def test_preparer_explicit_product_is_not_replaced_by_policy_default() -> None:
    risk = _RecordingRiskEngine()
    explicit_context = replace(
        _execution_context(),
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    decoy_policy = ProductSelectionPolicy(
        market_pack_id="india-equity",
        rule_version="india-products-v1",
        rules=(
            ProductSelectionRule(
                _market(),
                ProductCode("MIS"),
                frozenset({ProductCode("MIS"), ProductCode("CNC")}),
            ),
        ),
    )

    result = _preparer(
        risk_engine=risk,
        product_selection=decoy_policy,
    ).prepare(
        _decision(product=ProductCode("CNC"), context=explicit_context),
        _event(),
        _financial_state(),
    )

    assert result.request is not None
    assert result.request.product == ProductCode("CNC")
    assert risk.contexts[0].product == ProductCode("CNC")
    assert risk.intents[0].product == ProductCode("CNC")


def test_preparer_resolves_auto_effect_before_risk_approval() -> None:
    risk = _RecordingRiskEngine()

    result = _preparer(
        risk_engine=risk,
        product_selection=INDIA_EQUITY_PRODUCT_SELECTION,
    ).prepare(
        _decision(
            side=OrderSide.SELL,
            quantity=Decimal("2"),
            position_effect=PositionEffect.AUTO,
        ),
        _event(),
        _financial_state(),
        position_evidence=_close_or_auto_evidence("5"),
        position_evidence_max_age=timedelta(minutes=5),
        approval_instant=_event().timestamp,
    )

    assert result.request is not None
    assert risk.contexts[0].effective_position_effect is PositionEffect.CLOSE
    assert result.request.effective_position_effect is PositionEffect.CLOSE
    assert result.request.position_evidence_cut == _event().timestamp
    assert result.request.position_effect is PositionEffect.AUTO


def test_preparer_live_omitted_product_stops_before_risk() -> None:
    risk = _RecordingRiskEngine()
    live_context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    live_deployment = replace(_deployment(), execution_mode=ExecutionMode.LIVE)
    decision = _decision(context=live_context)
    live_decision = StrategyExecutionDecision(
        live_deployment,
        StrategyResult(decision.result.signal, decision.result.intent),
    )

    with pytest.raises(ProductSelectionError, match="live execution requires a resolved product"):
        _preparer(risk_engine=risk).prepare(live_decision, _event(), _financial_state())

    assert risk.contexts == []


def test_preparer_unresolvable_market_stops_before_risk() -> None:
    risk = _RecordingRiskEngine()
    bse_only = ProductSelectionPolicy(
        market_pack_id="india-equity",
        rule_version="india-products-v1",
        rules=(
            ProductSelectionRule(
                MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"),
                ProductCode("CNC"),
            ),
        ),
    )

    with pytest.raises(ProductSelectionError, match="no versioned default product"):
        _preparer(risk_engine=risk, product_selection=bse_only).prepare(
            _decision(), _event(), _financial_state()
        )

    assert risk.contexts == []


def test_preparer_conflicting_pack_identity_stops_before_risk() -> None:
    risk = _RecordingRiskEngine()
    conflicting = replace(
        _execution_context(),
        market_pack_id="other-pack",
        rule_version="india-products-v1",
    )

    with pytest.raises(ProductSelectionError, match="market-pack id conflicts"):
        _preparer(
            risk_engine=risk,
            product_selection=INDIA_EQUITY_PRODUCT_SELECTION,
        ).prepare(
            _decision(context=conflicting),
            _event(),
            _financial_state(),
        )

    assert risk.contexts == []


def test_preparer_explicit_product_without_versioned_policy_stops_before_risk() -> None:
    risk = _RecordingRiskEngine()

    with pytest.raises(ProductSelectionError, match="requires a versioned market-pack"):
        _preparer(risk_engine=risk).prepare(
            _decision(product=ProductCode("CNC")),
            _event(),
            _financial_state(),
        )

    assert risk.contexts == []

    assert risk.contexts == []
