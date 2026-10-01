from decimal import Decimal

import pytest

from quantx.domain.finance import CapitalSourceType
from quantx.domain.value_objects import Money
from quantx.execution.account_financial_state import AccountFinancialStateBuilder


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "INR")


def test_builder_aggregates_explicit_cash_margin_pnl_and_exposure() -> None:
    snapshot = AccountFinancialStateBuilder().build(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=_money("9000"),
        available_cash=_money("8500"),
        blocked_cash=_money("500"),
        margin_used=_money("1000"),
        margin_available=_money("4000"),
        buying_power=_money("8500"),
        daily_pnl=_money("-75"),
        realized_pnl=_money("25"),
        unrealized_pnl=_money("-100"),
        gross_exposure=_money("5000"),
    )

    assert snapshot.state.cash_balance.amount == Decimal("9000")
    assert snapshot.state.available_cash.amount == Decimal("8500")
    assert snapshot.state.blocked_cash.amount == Decimal("500")
    assert snapshot.state.margin_used.amount == Decimal("1000")
    assert snapshot.state.margin_available.amount == Decimal("4000")
    assert snapshot.state.buying_power.amount == Decimal("8500")
    assert snapshot.daily_pnl.amount == Decimal("-75")
    assert snapshot.realized_pnl.amount == Decimal("25")
    assert snapshot.unrealized_pnl.amount == Decimal("-100")
    assert snapshot.gross_exposure.amount == Decimal("5000")


def test_from_cash_and_margin_does_not_invent_leverage() -> None:
    snapshot = AccountFinancialStateBuilder().from_cash_and_margin(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=_money("10000"),
        margin_used=_money("2000"),
        margin_available=_money("3000"),
        daily_pnl=_money("0"),
        realized_pnl=_money("0"),
        unrealized_pnl=_money("0"),
        gross_exposure=_money("4000"),
    )

    assert snapshot.state.available_cash.amount == Decimal("10000")
    assert snapshot.state.blocked_cash.amount == Decimal("0")
    assert snapshot.state.buying_power.amount == Decimal("10000")
    assert snapshot.state.margin_available.amount == Decimal("3000")


def test_builder_rejects_cash_conservation_violation() -> None:
    with pytest.raises(ValueError, match="cannot exceed cash_balance"):
        AccountFinancialStateBuilder().build(
            capital_source=CapitalSourceType.PAPER_CONFIGURED,
            cash_balance=_money("100"),
            available_cash=_money("80"),
            blocked_cash=_money("30"),
            margin_used=_money("0"),
            margin_available=_money("0"),
            buying_power=_money("80"),
            daily_pnl=_money("0"),
            realized_pnl=_money("0"),
            unrealized_pnl=_money("0"),
            gross_exposure=_money("0"),
        )


def test_builder_rejects_currency_mismatch() -> None:
    with pytest.raises(ValueError, match="one currency"):
        AccountFinancialStateBuilder().build(
            capital_source=CapitalSourceType.PAPER_CONFIGURED,
            cash_balance=_money("100"),
            available_cash=Money(Decimal("100"), "USD"),
            blocked_cash=_money("0"),
            margin_used=_money("0"),
            margin_available=_money("0"),
            buying_power=_money("100"),
            daily_pnl=_money("0"),
            realized_pnl=_money("0"),
            unrealized_pnl=_money("0"),
            gross_exposure=_money("0"),
        )
