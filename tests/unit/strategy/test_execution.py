from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
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
from quantx.domain.strategy import (
    SignalAction,
    StrategyId,
    StrategyResult,
    StrategySignal,
)
from quantx.domain.value_objects import Money
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.execution import StrategyExecutionPreparer


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _event() -> MarketDataEvent:
    instrument = InstrumentId("NSE", "TCS")
    timestamp = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
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
) -> StrategyExecutionDecision:
    event = _event()
    signal = StrategySignal(
        strategy_id=StrategyId("buy-and-hold"),
        strategy_version="1",
        instrument=event.instrument,
        action=SignalAction.BUY,
        confidence=1.0,
        generated_at=event.timestamp,
    )
    intent = TradeIntent(
        instrument=event.instrument,
        side=OrderSide.BUY,
        quantity=quantity,
        required_margin=required_margin,
        required_capabilities=required_capabilities,
        strategy_id="buy-and-hold",
        strategy_version="1",
        execution_context=_execution_context(),
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


def _preparer() -> StrategyExecutionPreparer:
    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
    return StrategyExecutionPreparer(InMemoryInstrumentRegistry((instrument,)))


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
        StrategyExecutionPreparer(InMemoryInstrumentRegistry()).prepare(
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
