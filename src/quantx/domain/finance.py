"""Account financial state and explicit capital-source primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .value_objects import Money


class CapitalSourceType(StrEnum):
    LIVE_BROKER = "live_broker"
    PAPER_CONFIGURED = "paper_configured"
    BACKTEST_CONFIGURED = "backtest_configured"


@dataclass(frozen=True, slots=True)
class AccountFinancialState:
    """Observed or configured financial state for one account.

    QuantX does not impose a universal minimum capital. Live values come from
    the broker; paper/backtest values must be explicitly configured.
    """

    capital_source: CapitalSourceType
    cash_balance: Money
    available_cash: Money
    blocked_cash: Money
    margin_used: Money
    margin_available: Money
    buying_power: Money

    def __post_init__(self) -> None:
        currencies = {
            self.cash_balance.currency,
            self.available_cash.currency,
            self.blocked_cash.currency,
            self.margin_used.currency,
            self.margin_available.currency,
            self.buying_power.currency,
        }
        if len(currencies) != 1:
            raise ValueError("all financial values must use the same currency")
        for name in (
            "cash_balance",
            "available_cash",
            "blocked_cash",
            "margin_used",
            "margin_available",
            "buying_power",
        ):
            if getattr(self, name).amount < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class BrokerConstraint:
    """Explicit broker/venue trading constraint, never a QuantX default."""

    name: str
    description: str
    minimum_order_value: Decimal | None = None
    minimum_quantity: Decimal | None = None
    minimum_margin: Money | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("constraint name must not be empty")
        if self.minimum_order_value is not None and self.minimum_order_value < 0:
            raise ValueError("minimum_order_value cannot be negative")
        if self.minimum_quantity is not None and self.minimum_quantity < 0:
            raise ValueError("minimum_quantity cannot be negative")
        if self.minimum_margin is not None and self.minimum_margin.amount < 0:
            raise ValueError("minimum_margin cannot be negative")
