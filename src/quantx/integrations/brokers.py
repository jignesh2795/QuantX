"""Broker/venue adapter capability contracts.

The core knows only capabilities and account-scoped connections. Concrete
broker implementations live in replaceable plugins and must not leak vendor
SDK types into the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import FrozenSet, Protocol
from uuid import UUID


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

    account_id: UUID
    connection_id: UUID
    broker_id: str
    market_context_id: str


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    values: FrozenSet[BrokerCapability] = frozenset()

    def supports(self, capability: BrokerCapability) -> bool:
        return capability in self.values

    def require(self, required: FrozenSet[BrokerCapability]) -> bool:
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
