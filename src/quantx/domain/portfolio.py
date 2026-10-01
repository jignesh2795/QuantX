"""Portfolio/accounting primitives for logical and physical portfolios."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .accounts import AccountId
from .instruments import InstrumentId, MarketContext
from .positions import Position
from .value_objects import Money
from .deployment import PortfolioId


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Point-in-time portfolio valuation using explicitly supplied values."""

    portfolio_id: PortfolioId
    valuation_currency: str
    cash: Money
    market_value: Money
    realized_pnl: Money
    unrealized_pnl: Money
    margin_used: Money

    def __post_init__(self) -> None:
        amounts = (
            self.cash,
            self.market_value,
            self.realized_pnl,
            self.unrealized_pnl,
            self.margin_used,
        )
        if any(value.currency != self.valuation_currency for value in amounts):
            raise ValueError("all snapshot values must use the valuation currency")

    @property
    def equity(self) -> Money:
        return Money(
            self.cash.amount + self.market_value.amount,
            self.valuation_currency,
        )


@dataclass(frozen=True, slots=True)
class PositionLedger:
    """Immutable collection of positions for one physical account/market."""

    account_id: AccountId
    market: MarketContext
    positions: tuple[Position, ...] = field(default_factory=tuple)

    def position_for(self, instrument_id: InstrumentId) -> Position | None:
        for position in self.positions:
            if position.instrument.instrument_id == instrument_id:
                return position
        return None


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Logical portfolio grouping one or more strategy/account exposures."""

    portfolio_id: PortfolioId
    name: str
    account_ids: tuple[AccountId, ...]
    market: MarketContext

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("portfolio name must not be empty")
        if not self.account_ids:
            raise ValueError("portfolio requires at least one account")

    def contains_account(self, account_id: AccountId) -> bool:
        return account_id in self.account_ids
