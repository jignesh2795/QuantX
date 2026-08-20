"""Registry for multiple broker connections per account and market."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .brokers import BrokerAdapter, BrokerCapability, BrokerConnectionRef, CapabilitySet


@dataclass(frozen=True, slots=True)
class RegisteredConnection:
    ref: BrokerConnectionRef
    adapter: BrokerAdapter
    enabled: bool = True


class AccountConnectionRegistry:
    """Keep broker connections isolated by account/connection identity."""

    def __init__(self) -> None:
        self._connections: dict[UUID, RegisteredConnection] = {}

    def register(self, connection: RegisteredConnection) -> None:
        if connection.ref.connection_id in self._connections:
            raise ValueError("broker connection already registered")
        self._connections[connection.ref.connection_id] = connection

    def get(self, connection_id: UUID) -> RegisteredConnection | None:
        return self._connections.get(connection_id)

    def for_account(self, account_id: UUID) -> tuple[RegisteredConnection, ...]:
        return tuple(
            item for item in self._connections.values()
            if item.ref.account_id == account_id and item.enabled
        )

    def candidates(
        self,
        account_id: UUID,
        required: frozenset[BrokerCapability],
    ) -> tuple[RegisteredConnection, ...]:
        return tuple(
            item
            for item in self.for_account(account_id)
            if item.adapter.capabilities().require(required)
            and item.adapter.health()
        )
