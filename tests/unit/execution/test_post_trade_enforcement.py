from decimal import Decimal

from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.value_objects import Money
from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer
from quantx.execution.post_trade_risk import PostTradeRiskLimits
from quantx.execution.trading_gate import TradingGate


def test_breach_trips_gate() -> None:
    gate = TradingGate()
    enforcer = PostTradeRiskEnforcer(
        limits=PostTradeRiskLimits(max_daily_loss=Money(Decimal("100"), "INR")),
        trading_gate=gate,
    )
    state = AccountFinancialState(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=Money(Decimal("900"), "INR"),
        available_cash=Money(Decimal("900"), "INR"),
        blocked_cash=Money.zero("INR"),
        margin_used=Money.zero("INR"),
        margin_available=Money(Decimal("1000"), "INR"),
        buying_power=Money(Decimal("900"), "INR"),
    )
    result = enforcer.evaluate(
        financial_state=state,
        daily_pnl=Money(Decimal("-101"), "INR"),
        gross_exposure=Money.zero("INR"),
    )
    assert result.breached
    assert not gate.allow()
    assert "maximum daily loss exceeded" in gate.state().reason
