from decimal import Decimal

import pytest

from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.value_objects import Money
from quantx.execution.account_financial_state import AccountFinancialStateBuilder
from quantx.execution.post_trade_risk import (
    PostTradeRiskEngine,
    PostTradeRiskLimits,
    PostTradeRiskSnapshot,
)


def _state(used: str, available: str) -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=Money(Decimal("10000"), "INR"),
        available_cash=Money(Decimal("8000"), "INR"),
        blocked_cash=Money(Decimal("2000"), "INR"),
        margin_used=Money(Decimal(used), "INR"),
        margin_available=Money(Decimal(available), "INR"),
        buying_power=Money(Decimal("8000"), "INR"),
    )


def test_daily_loss_limit_breaches() -> None:
    result = PostTradeRiskEngine().evaluate(
        PostTradeRiskSnapshot(
            _state("1000", "9000"), Money(Decimal("-501"), "INR"), Money(Decimal("1000"), "INR")
        ),
        PostTradeRiskLimits(max_daily_loss=Money(Decimal("500"), "INR")),
    )
    assert result.breached
    assert result.reasons == ("maximum daily loss exceeded",)


def test_margin_utilization_limit_breaches() -> None:
    result = PostTradeRiskEngine().evaluate(
        PostTradeRiskSnapshot(
            _state("7000", "3000"), Money(Decimal("0"), "INR"), Money(Decimal("1000"), "INR")
        ),
        PostTradeRiskLimits(max_margin_utilization=Decimal("0.6")),
    )
    assert result.breached


def test_exposure_limit_breaches_and_currency_mismatch_is_rejected() -> None:
    engine = PostTradeRiskEngine()
    result = engine.evaluate(
        PostTradeRiskSnapshot(
            _state("100", "9900"), Money(Decimal("0"), "INR"), Money(Decimal("5001"), "INR")
        ),
        PostTradeRiskLimits(max_exposure=Money(Decimal("5000"), "INR")),
    )
    assert result.reasons == ("maximum gross exposure exceeded",)

    with pytest.raises(ValueError, match="currency"):
        engine.evaluate(
            PostTradeRiskSnapshot(
                _state("100", "9900"), Money(Decimal("0"), "USD"), Money(Decimal("1"), "INR")
            ),
            PostTradeRiskLimits(max_daily_loss=Money(Decimal("500"), "INR")),
        )


def test_single_position_exposure_limit() -> None:
    state = AccountFinancialStateBuilder().from_cash_and_margin(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("0"), "INR"),
        daily_pnl=Money(Decimal("0"), "INR"),
        realized_pnl=Money(Decimal("0"), "INR"),
        unrealized_pnl=Money(Decimal("0"), "INR"),
        gross_exposure=Money(Decimal("1500"), "INR"),
        position_exposures=(
            Money(Decimal("1000"), "INR"),
            Money(Decimal("500"), "INR"),
        ),
    )
    result = PostTradeRiskEngine().evaluate(
        PostTradeRiskSnapshot(
            financial_state=state.state,
            daily_pnl=state.daily_pnl,
            gross_exposure=state.gross_exposure,
            position_exposures=state.position_exposures,
        ),
        PostTradeRiskLimits(max_position_exposure=Money(Decimal("900"), "INR")),
    )
    assert result.breached
    assert result.reasons == ("maximum single-position exposure exceeded",)


def test_max_open_positions_limit() -> None:
    state = AccountFinancialStateBuilder().from_cash_and_margin(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("0"), "INR"),
        daily_pnl=Money(Decimal("0"), "INR"),
        realized_pnl=Money(Decimal("0"), "INR"),
        unrealized_pnl=Money(Decimal("0"), "INR"),
        gross_exposure=Money(Decimal("1500"), "INR"),
        position_exposures=(
            Money(Decimal("1000"), "INR"),
            Money(Decimal("500"), "INR"),
        ),
    )
    result = PostTradeRiskEngine().evaluate(
        PostTradeRiskSnapshot(
            state.state, state.daily_pnl, state.gross_exposure, state.position_exposures
        ),
        PostTradeRiskLimits(max_open_positions=1),
    )
    assert result.breached
    assert result.reasons == ("maximum open positions exceeded",)
