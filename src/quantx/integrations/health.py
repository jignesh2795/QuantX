"""Broker connection health and capability freshness boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .brokers import BrokerCapability, BrokerConnectionRef


class ConnectionHealth(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    connection: BrokerConnectionRef
    capabilities: frozenset[BrokerCapability]
    observed_at: datetime
    source_version: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source_version.strip():
            raise ValueError("source_version must not be empty")


@dataclass(frozen=True, slots=True)
class ConnectionHealthSnapshot:
    connection: BrokerConnectionRef
    status: ConnectionHealth
    observed_at: datetime
    latency_ms: int | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")


class ConnectionHealthRegistry:
    """Operational connection evidence kept outside immutable account identity."""

    def __init__(self) -> None:
        self._health: dict[str, ConnectionHealthSnapshot] = {}
        self._capabilities: dict[str, CapabilitySnapshot] = {}

    def set_health(self, snapshot: ConnectionHealthSnapshot) -> None:
        self._health[str(snapshot.connection.connection_id)] = snapshot

    def health(self, connection: BrokerConnectionRef) -> ConnectionHealthSnapshot | None:
        return self._health.get(str(connection.connection_id))

    def set_capabilities(self, snapshot: CapabilitySnapshot) -> None:
        self._capabilities[str(snapshot.connection.connection_id)] = snapshot

    def capabilities(self, connection: BrokerConnectionRef) -> CapabilitySnapshot | None:
        return self._capabilities.get(str(connection.connection_id))
