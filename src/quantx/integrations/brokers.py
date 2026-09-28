"""Broker/venue adapter capability contracts.

The core knows only capabilities and account-scoped connections. Concrete
broker implementations live in replaceable plugins and must not leak vendor
SDK types into the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import FrozenSet, Protocol

from quantx.domain.value_objects import AccountId, BrokerConnectionId


class BrokerCapability(StrEnum):
    MARKET_DATA = "MARKET_DATA"
    ORDER_SUBMISSION = "ORDER_SUBMISSION"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    ORDER_REPLACEMENT = "ORDER_REPLACEMENT"
    POSITIONS = "POSITIONS"
    BALANCES = "BALANCES"
    DERIVATIVES = "DERIVATIVES"
    OPTIONS = "OPTIONS"
    SHORT_SELLING = "SHORT_SELLING"
    FRACTIONAL_QUANTITY = "FRACTIONAL_QUANTITY"
    PAPER_TRADING = "PAPER_TRADING"


@dataclass(frozen=True, slots=True)
class BrokerConnectionRef:
    """Account-scoped connection identity, not a reusable global credential."""

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    market_context_id: str

    def __post_init__(self) -> None:
        if not self.broker_id.strip():
            raise ValueError("broker_id must not be empty")
        if not self.market_context_id.strip():
            raise ValueError("market_context_id must not be empty")


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    values: FrozenSet[BrokerCapability] = frozenset()

    def supports(self, capability: BrokerCapability) -> bool:
        return capability in self.values

    def require(self, required: FrozenSet[str]) -> bool:
        return required.issubset(self.values)


@dataclass(frozen=True, slots=True)
class BrokerDescriptor:
    broker_id: str
    display_name: str
    capabilities: CapabilitySet
    adapter_version: str


class BrokerAdapter(Protocol):
    """Minimal adapter boundary used by execution/routing infrastructure."""

    @property
    def descriptor(self) -> BrokerDescriptor: ...

    @property
    def connection(self) -> BrokerConnectionRef: ...

    def health(self) -> bool: ...

    def capabilities(self) -> CapabilitySet: ...
