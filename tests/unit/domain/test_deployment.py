import pytest

from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.value_objects import AccountId, BrokerConnectionId


def _default_context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("conn-live-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="test-pack",
        rule_version="test-v1",
    )


@pytest.mark.parametrize(
    "mode",
    [
        ExecutionMode.BACKTEST,
        ExecutionMode.REPLAY,
        ExecutionMode.SHADOW,
        ExecutionMode.PAPER,
        ExecutionMode.LIVE,
    ],
)
def test_execution_context_accepts_exact_mode(mode: ExecutionMode) -> None:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=mode,
    )
    assert type(context.execution_mode) is ExecutionMode
    assert context.execution_mode is mode


@pytest.mark.parametrize(
    "bad_mode",
    [
        pytest.param("live", id="str-live"),
        pytest.param("LIVE", id="uppercase-str"),
        pytest.param("paper", id="str-paper"),
        pytest.param("PAPER", id="uppercase-paper"),
        pytest.param(ExecutionMode.LIVE.value, id="live-value-str"),
        pytest.param(ExecutionMode.PAPER.value, id="paper-value-str"),
        pytest.param(None, id="none"),
        pytest.param(7, id="int"),
    ],
)
def test_execution_context_rejects_non_enum_mode(bad_mode) -> None:
    with pytest.raises(ValueError) as exc_info:
        ExecutionContext(
            account_id=AccountId("acct-1"),
            portfolio_id=PortfolioId("portfolio-1"),
            deployment_id=StrategyDeploymentId("deploy-1"),
            market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
            broker_connection_id=None,
            execution_mode=bad_mode,
        )
    assert str(exc_info.value) == "execution_context.execution_mode must be exact ExecutionMode"


def test_execution_context_subclass_is_not_constructible() -> None:
    with pytest.raises((TypeError, AttributeError)):
        type("_Sub", (ExecutionMode,), {"LIVE": "live"})
