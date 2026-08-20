"""Account, broker-connection, and ownership domain primitives.

Accounts are intentionally independent from strategies and market contexts so one
QuantX installation can operate multiple broker accounts at the same time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class AccountOwnerType(str, Enum):
    INDIVIDUAL = "individual"
    FAMILY = "family"
    ORGANIZATION = "organization"


class AccountRole(str, Enum):
    PRIMARY = "primary"
    MEMBER = "member"
    MANAGED = "managed"


@dataclass(frozen=True, slots=True)
class AccountId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("account id must not be empty")


@dataclass(frozen=True, slots=True)
class BrokerConnectionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("broker connection id must not be empty")


@dataclass(frozen=True, slots=True)
class Account:
    """Logical trading account owned by a person, family, or organization."""

    account_id: AccountId
    display_name: str
    owner_type: AccountOwnerType
    role: AccountRole = AccountRole.PRIMARY
    tags: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")


@dataclass(frozen=True, slots=True)
class BrokerConnection:
    """A distinct authenticated broker session/configuration for an account.

    Multiple connections may exist simultaneously for the same account family,
    broker, or market. Secrets are referenced indirectly; they are not stored in
    this domain object.
    """

    connection_id: BrokerConnectionId
    account_id: AccountId
    broker: str
    profile_name: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.broker.strip():
            raise ValueError("broker must not be empty")
        if not self.profile_name.strip():
            raise ValueError("profile_name must not be empty")
