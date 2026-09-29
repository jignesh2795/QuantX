"""Coherent account financial-state aggregation.

This module combines explicit cash, margin, P&L, and exposure inputs into one
account snapshot. It deliberately does not invent broker buying-power,
margin, or exposure rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.value_objects import Money


@dataclass(frozen=True, slots=True)
class AccountFinancialSnapshot:
    """One internally consistent account-level financial observation."""

    state: AccountFinancialState
    daily_pnl: Money
    realized_pnl: Money
    unrealized_pnl: Money
    gross_exposure: Money

    def __post_init__(self) -> None:
        currencies = {
            self.state.cash_balance.currency,
            self.daily_pnl.currency,
            self.realized_pnl.currency,
            self.unrealized_pnl.currency,
            self.gross_exposure.currency,
        }
        if len(currencies) != 1:
            raise ValueError("all account financial values must use the same currency")
        if self.gross_exposure.amount < 0:
            raise ValueError("gross_exposure cannot be negative")


class AccountFinancialStateBuilder:
    """Build account financial state from explicit runtime observations.

    available_cash, blocked_cash, and buying_power are supplied by the caller
    because their meaning is venue/policy dependent. The builder only
    validates their accounting relationship and combines them with the
    supplied margin and P&L observations.
    """

    def build(
        self,
        *,
        capital_source: CapitalSourceType,
        cash_balance: Money,
        available_cash: Money,
        blocked_cash: Money,
        margin_used: Money,
        margin_available: Money,
        buying_power: Money,
        daily_pnl: Money,
        realized_pnl: Money,
        unrealized_pnl: Money,
        gross_exposure: Money,
    ) -> AccountFinancialSnapshot:
        values = (
            available_cash,
            blocked_cash,
            margin_used,
            margin_available,
            buying_power,
            daily_pnl,
            realized_pnl,
            unrealized_pnl,
            gross_exposure,
        )
        if any(value.currency != cash_balance.currency for value in values):
            raise ValueError("all account financial values must use one currency")

        if available_cash.amount + blocked_cash.amount > cash_balance.amount:
            raise ValueError("available_cash plus blocked_cash cannot exceed cash_balance")

        return AccountFinancialSnapshot(
            state=AccountFinancialState(
                capital_source=capital_source,
                cash_balance=cash_balance,
                available_cash=available_cash,
                blocked_cash=blocked_cash,
                margin_used=margin_used,
                margin_available=margin_available,
                buying_power=buying_power,
            ),
            daily_pnl=daily_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            gross_exposure=gross_exposure,
        )

    def from_cash_and_margin(
        self,
        *,
        capital_source: CapitalSourceType,
        cash_balance: Money,
        margin_used: Money,
        margin_available: Money,
        daily_pnl: Money,
        realized_pnl: Money,
        unrealized_pnl: Money,
        gross_exposure: Money,
        blocked_cash: Money | None = None,
    ) -> AccountFinancialSnapshot:
        """Build a conservative paper-style state from explicit ledgers.

        With no separate cash-reservation ledger, blocked cash defaults to
        zero. Buying power is deliberately limited to available cash rather
        than adding margin availability or assuming leverage.
        """
        blocked = blocked_cash or Money.zero(cash_balance.currency)
        available = Money(cash_balance.amount - blocked.amount, cash_balance.currency)
        if available.amount < Decimal("0"):
            raise ValueError("blocked_cash cannot exceed cash_balance")
        return self.build(
            capital_source=capital_source,
            cash_balance=cash_balance,
            available_cash=available,
            blocked_cash=blocked,
            margin_used=margin_used,
            margin_available=margin_available,
            buying_power=available,
            daily_pnl=daily_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            gross_exposure=gross_exposure,
        )
