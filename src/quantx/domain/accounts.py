"""Account and broker-connection identity primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .finance import CapitalSource, CapitalSourceType
from .instruments import MarketContext
from .value_objects import AccountId, BrokerConnectionId

__all__ = [
    "Account",
    "AccountMarketProfile",
    "AccountOwnerType",
    "AccountRole",
    "BrokerConnection",
    "CapitalSource",
    "CapitalSourceType",
    "ConnectionStatus",
    "Owner",
]


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
    account_id: AccountId
    market: MarketContext
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class BrokerConnection:
    connection_id: BrokerConnectionId
    account_id: AccountId
    broker: str
    profile_name: str
    market: MarketContext
    status: ConnectionStatus = ConnectionStatus.UNCONFIGURED
    capabilities: frozenset[str] = frozenset()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.broker.strip():
            raise ValueError("broker must not be empty")
        if not self.profile_name.strip():
            raise ValueError("profile_name must not be empty")

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities
