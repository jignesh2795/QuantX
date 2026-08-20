"""Account-safe broker routing and explicit failover semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from uuid import UUID

from .account_registry import AccountConnectionRegistry, RegisteredConnection
from .brokers import BrokerCapability


class RoutingDisposition(StrEnum):
    ROUTED = "ROUTED"
    NO_ROUTE = "NO_ROUTE"
    FAILOVER_BLOCKED = "FAILOVER_BLOCKED"


class FailoverReason(StrEnum):
    NONE = "NONE"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    MARKET_MISMATCH = "MARKET_MISMATCH"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    account_id: UUID
    market_context_id: str
    required_capabilities: frozenset[BrokerCapability]
    preferred_connection_id: UUID | None = None
    allow_failover: bool = True

    def __post_init__(self) -> None:
        if not self.market_context_id.strip():
            raise ValueError("market_context_id must not be empty")


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    disposition: RoutingDisposition
    connection: RegisteredConnection | None
    reason: FailoverReason = FailoverReason.NONE
    considered_connection_ids: tuple[UUID, ...] = ()


class AccountAwareRouter:
    """Select an execution connection without crossing account or market boundaries."""

    def __init__(
        self,
        registry: AccountConnectionRegistry,
        health_check: Callable[[RegisteredConnection], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._health_check = health_check or (lambda item: item.adapter.health())

    def route(self, request: RoutingRequest) -> RoutingDecision:
        connections = self._registry.for_account(request.account_id)
        considered: list[UUID] = []

        if request.preferred_connection_id is not None:
            preferred = self._registry.get(request.preferred_connection_id)
            if preferred is None:
                return RoutingDecision(
                    RoutingDisposition.FAILOVER_BLOCKED,
                    None,
                    FailoverReason.ACCOUNT_MISMATCH,
                    (),
                )
            considered.append(preferred.ref.connection_id)
            if preferred.ref.account_id != request.account_id:
                return RoutingDecision(
                    RoutingDisposition.FAILOVER_BLOCKED,
                    None,
                    FailoverReason.ACCOUNT_MISMATCH,
                    tuple(considered),
                )
            if preferred.ref.market_context_id != request.market_context_id:
                return RoutingDecision(
                    RoutingDisposition.FAILOVER_BLOCKED,
                    None,
                    FailoverReason.MARKET_MISMATCH,
                    tuple(considered),
                )
            if not preferred.adapter.capabilities().require(request.required_capabilities):
                return RoutingDecision(
                    RoutingDisposition.FAILOVER_BLOCKED,
                    None,
                    FailoverReason.CAPABILITY_MISMATCH,
                    tuple(considered),
                )
            if self._health_check(preferred):
                return RoutingDecision(RoutingDisposition.ROUTED, preferred, considered_connection_ids=tuple(considered))
            if not request.allow_failover:
                return RoutingDecision(
                    RoutingDisposition.FAILOVER_BLOCKED,
                    None,
                    FailoverReason.HEALTH_UNAVAILABLE,
                    tuple(considered),
                )

        for candidate in connections:
            if candidate.ref.connection_id in considered:
                continue
            considered.append(candidate.ref.connection_id)
            if candidate.ref.market_context_id != request.market_context_id:
                continue
            if not candidate.adapter.capabilities().require(request.required_capabilities):
                continue
            if not self._health_check(candidate):
                continue
            return RoutingDecision(
                RoutingDisposition.ROUTED,
                candidate,
                considered_connection_ids=tuple(considered),
            )

        return RoutingDecision(
            RoutingDisposition.NO_ROUTE,
            None,
            FailoverReason.HEALTH_UNAVAILABLE,
            tuple(considered),
        )
