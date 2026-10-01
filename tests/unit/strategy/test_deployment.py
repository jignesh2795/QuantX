from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.deployment import StrategyDeploymentRuntime
from quantx.strategy.registry import StrategyRegistry
from quantx.strategy.reference import BuyAndHoldStrategy


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


def _ir():
    return StrategyCompiler.compile(
        StrategyDefinition(StrategyId("buy-and-hold"), "1", "Buy and Hold")
    )


def _deployment(*, enabled: bool = True, strategy_id: str = "buy-and-hold", version: str = "1"):
    return StrategyDeployment(
        deployment_id=StrategyDeploymentId("deploy-1"),
        strategy_id=strategy_id,
        strategy_version=version,
        portfolio_id=PortfolioId("portfolio-1"),
        account_id=AccountId("acct-1"),
        market=_market(),
        execution_mode=ExecutionMode.PAPER,
        enabled=enabled,
    )


def _runtime() -> StrategyDeploymentRuntime:
    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", BuyAndHoldStrategy)
    return StrategyDeploymentRuntime(registry)


def test_deployment_runtime_resolves_strategy_and_evaluates() -> None:
    decision = _runtime().evaluate(_deployment(), _ir(), _event())

    assert decision.deployment == _deployment()
    assert decision.result.signal.strategy_id == StrategyId("buy-and-hold")
    assert decision.result.intent is not None
    assert decision.result.intent.instrument == _event().instrument


def test_deployment_runtime_rejects_disabled_deployment() -> None:
    with pytest.raises(ValueError, match="disabled"):
        _runtime().evaluate(_deployment(enabled=False), _ir(), _event())


def test_deployment_runtime_rejects_strategy_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="strategy id"):
        _runtime().evaluate(_deployment(strategy_id="other"), _ir(), _event())


def test_deployment_runtime_rejects_version_mismatch() -> None:
    with pytest.raises(ValueError, match="strategy version"):
        _runtime().evaluate(_deployment(version="2"), _ir(), _event())


def test_deployment_runtime_rejects_market_venue_mismatch() -> None:
    wrong_event = MarketDataEvent(
        MarketDataType.QUOTE,
        _event().timestamp,
        InstrumentId("BSE", "TCS"),
        Quote(
            InstrumentId("BSE", "TCS"),
            _event().timestamp,
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
    )
    with pytest.raises(ValueError, match="market venue"):
        _runtime().evaluate(_deployment(), _ir(), wrong_event)


def test_deployment_runtime_resolves_fresh_strategy_instances() -> None:
    registry = StrategyRegistry()
    registry.register("buy-and-hold", "1", BuyAndHoldStrategy)
    runtime = StrategyDeploymentRuntime(registry)

    first = runtime.evaluate(_deployment(), _ir(), _event())
    second = runtime.evaluate(_deployment(), _ir(), _event())

    assert first.result.signal.signal_id != second.result.signal.signal_id
