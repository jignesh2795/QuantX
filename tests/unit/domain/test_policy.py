from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.capabilities import Capability
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext, PolicyDecision
from quantx.domain.value_objects import InstrumentId


def _intent(
    mode: ExecutionMode = ExecutionMode.PAPER, approval_required: bool = False
) -> TradeIntent:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=mode,
    )
    return TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        execution_context=context,
        approval_required=approval_required,
        required_capabilities=frozenset({Capability.READ_MARKET_DATA.value}),
    )


def test_paper_policy_allows_granted_capabilities() -> None:
    result = ExecutionPolicyEngine().evaluate(
        _intent(),
        PolicyContext(granted_capabilities=frozenset({Capability.READ_MARKET_DATA.value})),
    )
    assert result.decision is PolicyDecision.APPROVE


def test_live_policy_fails_closed_when_live_trading_is_disabled() -> None:
    result = ExecutionPolicyEngine().evaluate(
        _intent(ExecutionMode.LIVE),
        PolicyContext(
            granted_capabilities=frozenset(
                {
                    Capability.CREATE_LIVE_ORDER.value,
                    Capability.EXECUTE_LIVE.value,
                    Capability.ACCESS_BROKER.value,
                }
            ),
            live_trading_enabled=False,
        ),
    )
    assert result.decision is PolicyDecision.REJECT


def test_live_policy_requires_all_execution_capabilities() -> None:
    result = ExecutionPolicyEngine().evaluate(
        _intent(ExecutionMode.LIVE),
        PolicyContext(
            granted_capabilities=frozenset({Capability.CREATE_LIVE_ORDER.value}),
            live_trading_enabled=True,
        ),
    )
    assert result.decision is PolicyDecision.REJECT
    assert Capability.EXECUTE_LIVE.value in result.missing_capabilities


def test_policy_can_require_manual_approval() -> None:
    result = ExecutionPolicyEngine().evaluate(
        _intent(approval_required=True),
        PolicyContext(granted_capabilities=frozenset({Capability.READ_MARKET_DATA.value})),
    )
    assert result.decision is PolicyDecision.APPROVAL_REQUIRED
