"""Ownership, account, market-profile, and broker-connection primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import FrozenSet, Optional

from .instruments import MarketContext
from .value_objects import Money


class AccountOwnerType(StrEnum):
    INDIVIDUAL = "individual"
    FAMILY = "family"
    ORGANIZATION = "organization"
    MANAGED_GROUP = "managed_group"


class AccountRole(StrEnum):
    PRIMARY = "primary"
    MEMBER = "member"
    MANAGED = "managed"


class ConnectionStatus(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    AUTHENTICATED = "authenticated"
    READY = "ready"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    DISABLED = "disabled"


class CapitalSourceType(StrEnum):
    LIVE_BROKER = "live_broker"
    PAPER_CONFIGURED = "paper_configured"


@dataclass(frozen=True, slots=True)
class AccountId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("account id must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BrokerConnectionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("broker connection id must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Owner:
    owner_id: str
    owner_type: AccountOwnerType
    display_name: str

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("owner_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")


@dataclass(frozen=True, slots=True)
class Account:
    """Logical trading account independent of broker implementation."""

    account_id: AccountId
    owner_id: str
    display_name: str
    role: AccountRole = AccountRole.PRIMARY
    base_currency: str = ""

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("owner_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")
        if not self.base_currency.strip():
            raise ValueError("base_currency must not be empty")


@dataclass(frozen=True, slots=True)
class AccountMarketProfile:
    """Market-specific capabilities/configuration for one logical account."""

    account_id: AccountId
    market: MarketContext
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class CapitalSource:
    """Declares where current capital is obtained at runtime.

    No minimum or default live capital is stored here. Live capital must be
    fetched from the connected broker; paper capital must be explicitly set by
    the paper environment.
    """

    source_type: CapitalSourceType
    connection_id: Optional[BrokerConnectionId] = None
    configured_balance: Optional[Money] = None

    def __post_init__(self) -> None:
        if self.source_type is CapitalSourceType.LIVE_BROKER:
            if self.connection_id is None:
                raise ValueError("LIVE_BROKER requires connection_id")
            if self.configured_balance is not None:
                raise ValueError("LIVE_BROKER cannot include configured_balance")
        elif self.source_type is CapitalSourceType.PAPER_CONFIGURED:
            if self.configured_balance is None:
                raise ValueError("PAPER_CONFIGURED requires configured_balance")
            if self.configured_balance.amount < Decimal("0"):
                raise ValueError("configured_balance cannot be negative")
            if self.connection_id is not None:
                raise ValueError("PAPER_CONFIGURED cannot include connection_id")


@dataclass(frozen=True, slots=True)
class BrokerConnection:
    """A distinct broker session/configuration for an account."""

    connection_id: BrokerConnectionId
    account_id: AccountId
    broker: str
    profile_name: str
    market: MarketContext
    status: ConnectionStatus = ConnectionStatus.UNCONFIGURED
    capabilities: FrozenSet[str] = frozenset()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.broker.strip():
            raise ValueError("broker must not be empty")
        if not self.profile_name.strip():
            raise ValueError("profile_name must not be empty")

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities
