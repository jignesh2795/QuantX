"""Strategy deployment, capital allocation, routing, and execution context."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .accounts import AccountId, BrokerConnectionId
from .instruments import MarketContext


class ExecutionMode(StrEnum):
    BACKTEST = "backtest"
    REPLAY = "replay"
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class PortfolioId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("portfolio id must not be empty")


@dataclass(frozen=True, slots=True)
class StrategyDeploymentId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("strategy deployment id must not be empty")


@dataclass(frozen=True, slots=True)
class Portfolio:
    portfolio_id: PortfolioId
    account_id: AccountId
    name: str
    market: MarketContext
    logical: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("portfolio name must not be empty")


@dataclass(frozen=True, slots=True)
class StrategyDeployment:
    deployment_id: StrategyDeploymentId
    strategy_id: str
    strategy_version: str
    portfolio_id: PortfolioId
    account_id: AccountId
    market: MarketContext
    execution_mode: ExecutionMode
    enabled: bool = False

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.strategy_version.strip():
            raise ValueError("strategy id and version are required")


@dataclass(frozen=True, slots=True)
class CapitalAllocation:
    deployment_id: StrategyDeploymentId
    amount: Decimal | None = None
    fraction: Decimal | None = None

    def __post_init__(self) -> None:
        if self.amount is None and self.fraction is None:
            raise ValueError("allocation requires amount or fraction")
        if self.amount is not None and self.amount < 0:
            raise ValueError("allocation amount cannot be negative")
        if self.fraction is not None and not Decimal("0") <= self.fraction <= Decimal("1"):
            raise ValueError("allocation fraction must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    name: str
    allowed_connection_ids: tuple[BrokerConnectionId, ...]
    failover_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("routing policy name must not be empty")
        if not self.allowed_connection_ids:
            raise ValueError("routing policy requires at least one broker connection")


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    account_id: AccountId
    portfolio_id: PortfolioId
    deployment_id: StrategyDeploymentId
    market: MarketContext
    broker_connection_id: BrokerConnectionId | None
    execution_mode: ExecutionMode
