"""Concrete production startup composition for pending LIVE recovery.

This module wires already-existing boundaries together without introducing
new registries, routers, or reconciliation frameworks:

durable ``UnitOfWork``
        -> ``PendingExecutionRecoveryRunner``
        -> exact account/connection resolution via ``AccountConnectionRegistry``
        -> caller-supplied read-only evidence providers
        -> existing reconciliation machinery
        -> ``ApplicationRuntime.start()``

Identity comes only from the persisted ``PendingExecutionContext``. There is
no default-account or default-connection fallback: an unresolvable identity
fails closed and the reservation stays pending. Nothing here submits broker
orders; evidence providers are read-only by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import PendingExecutionRecoveryRequest
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import AccountConnectionRegistry
from quantx.integrations.brokers import BrokerAdapter
from quantx.persistence import UnitOfWork

from .evidence_refresh import (
    DefinitiveEvidencePolicy,
    ReconciliationEvidenceProvider,
    RefreshPolicy,
)
from .pending_recovery import (
    FillProvider,
    LocalAccountProvider,
    LocalOrderProvider,
    LocalPositionProvider,
    PendingExecutionRecoveryRunner,
)
from .runtime import ApplicationRuntime

RecoveryEvidenceFactory = Callable[
    [BrokerAdapter, PendingExecutionRecoveryRequest],
    ReconciliationEvidenceProvider,
]
"""Build a read-only evidence provider for one bound adapter and request."""


@dataclass(frozen=True, slots=True)
class ResolvedRecoveryEndpoint:
    """A recovery provider bound to exact persisted account/connection/broker identity."""

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    adapter: BrokerAdapter
    evidence_provider: ReconciliationEvidenceProvider


class RecoveryEndpointResolver:
    """Resolve recovery evidence providers by exact persisted identity.

    Resolution is a pure registry lookup on the persisted broker connection
    id, followed by explicit equality checks on account, connection, and
    (optionally) broker identity. Anything else fails closed.
    """

    def __init__(
        self,
        registry: AccountConnectionRegistry,
        evidence_factory: RecoveryEvidenceFactory,
        *,
        expected_broker_id: str | None = None,
    ) -> None:
        if expected_broker_id is not None and not expected_broker_id.strip():
            raise ValueError("expected broker id must not be empty")
        self._registry = registry
        self._evidence_factory = evidence_factory
        self._expected_broker_id = expected_broker_id

    def resolve(self, request: PendingExecutionRecoveryRequest) -> ResolvedRecoveryEndpoint:
        """Bind one recovery request to its registered adapter and provider."""
        context = request.execution_context
        if context.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("pending recovery resolution requires LIVE execution context")
        connection_id = context.broker_connection_id
        if connection_id is None:
            raise ValueError("pending recovery requires a broker connection identity")
        registered = self._registry.get(connection_id)
        if registered is None:
            raise ValueError(f"unknown broker connection: {connection_id}")
        if not registered.enabled:
            raise ValueError(f"broker connection is disabled: {connection_id}")
        if registered.ref.account_id != context.account_id:
            raise ValueError("registered connection account does not match recovery account")
        if self._expected_broker_id is not None and (
            registered.ref.broker_id != self._expected_broker_id
        ):
            raise ValueError("registered broker does not match expected recovery broker")
        adapter = registered.adapter
        if adapter.connection != registered.ref:
            raise ValueError("broker adapter connection drifted from registry")
        return ResolvedRecoveryEndpoint(
            account_id=context.account_id,
            connection_id=connection_id,
            broker_id=registered.ref.broker_id,
            adapter=adapter,
            evidence_provider=self._evidence_factory(adapter, request),
        )

    def resolve_provider(
        self, request: PendingExecutionRecoveryRequest
    ) -> ReconciliationEvidenceProvider:
        """Adapt endpoint resolution to the runner's provider-resolver slot."""
        return self.resolve(request).evidence_provider


def build_application_runtime(
    *,
    unit_of_work: UnitOfWork,
    registry: AccountConnectionRegistry,
    evidence_factory: RecoveryEvidenceFactory,
    expected_broker_id: str | None = None,
    local_order_provider: LocalOrderProvider | None = None,
    local_position_provider: LocalPositionProvider | None = None,
    local_account_provider: LocalAccountProvider | None = None,
    fill_provider: FillProvider | None = None,
    evidence_policy: DefinitiveEvidencePolicy | None = None,
    refresh_policy: RefreshPolicy | None = None,
) -> ApplicationRuntime:
    """Compose durable recovery infrastructure into the one-shot startup runtime.

    Local providers are optional caller-supplied evidence sources; when absent,
    the corresponding evidence stays explicitly unavailable and the existing
    ``DefinitiveEvidencePolicy`` machinery keeps the reservation pending.
    """
    resolver = RecoveryEndpointResolver(
        registry,
        evidence_factory,
        expected_broker_id=expected_broker_id,
    )
    runner = PendingExecutionRecoveryRunner(
        unit_of_work=unit_of_work,
        provider_resolver=resolver.resolve_provider,
        local_order_provider=local_order_provider,
        local_position_provider=local_position_provider,
        local_account_provider=local_account_provider,
        fill_provider=fill_provider,
        evidence_policy=evidence_policy,
        refresh_policy=refresh_policy,
    )
    return ApplicationRuntime(pending_recovery=runner)


__all__ = [
    "RecoveryEndpointResolver",
    "RecoveryEvidenceFactory",
    "ResolvedRecoveryEndpoint",
    "build_application_runtime",
]
