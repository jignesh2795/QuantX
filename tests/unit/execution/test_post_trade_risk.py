from decimal import Decimal

import pytest

from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.value_objects import Money
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
        PostTradeRiskSnapshot(_state("1000", "9000"), Money(Decimal("-501"), "INR"), Money(Decimal("1000"), "INR")),
        PostTradeRiskLimits(max_daily_loss=Money(Decimal("500"), "INR")),
    )
    assert result.breached
    assert result.reasons == ("maximum daily loss exceeded",)


def test_margin_utilization_limit_breaches() -> None:
    result = PostTradeRiskEngine().evaluate(
        PostTradeRiskSnapshot(_state("7000", "3000"), Money(Decimal("0"), "INR"), Money(Decimal("1000"), "INR")),
        PostTradeRiskLimits(max_margin_utilization=Decimal("0.6")),
    )
    assert result.breached


def test_exposure_limit_breaches_and_currency_mismatch_is_rejected() -> None:
    engine = PostTradeRiskEngine()
    result = engine.evaluate(
        PostTradeRiskSnapshot(_state("100", "9900"), Money(Decimal("0"), "INR"), Money(Decimal("5001"), "INR")),
        PostTradeRiskLimits(max_exposure=Money(Decimal("5000"), "INR")),
    )
    assert result.reasons == ("maximum gross exposure exceeded",)

    with pytest.raises(ValueError, match="currency"):
        engine.evaluate(
            PostTradeRiskSnapshot(_state("100", "9900"), Money(Decimal("0"), "USD"), Money(Decimal("1"), "INR")),
            PostTradeRiskLimits(max_daily_loss=Money(Decimal("500"), "INR")),
        )
