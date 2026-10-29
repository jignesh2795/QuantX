"""Shared factories for LIVE risk-evidence source-trust tests.

The registry adapter here only registers a connection; it never submits. Tests
that submit use their own fake broker. Trust is established the way a
deployment establishes it: an explicit builder registered in an
application-owned catalog over a connection this process registered.
"""

from __future__ import annotations

from quantx.application.live_risk_evidence import LiveRiskEvidenceSource
from quantx.application.live_risk_sources import (
    LiveRiskEvidenceSourceBuilder,
    LiveRiskEvidenceSourceCatalog,
    TrustedLiveRiskEvidenceBinding,
)
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import AccountConnectionRegistry, RegisteredConnection
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)

BROKER_ID = "fake"


class RegistryAdapter:
    """Minimal BrokerAdapter: registers a connection identity, nothing more."""

    def __init__(self, connection: BrokerConnectionRef) -> None:
        capabilities = CapabilitySet(frozenset({BrokerCapability.ORDER_SUBMISSION}))
        self._connection = connection
        self.descriptor = BrokerDescriptor(BROKER_ID, "Fake", capabilities, "1")

    @property
    def connection(self) -> BrokerConnectionRef:
        return self._connection

    def health(self) -> bool:
        return True

    def capabilities(self) -> CapabilitySet:
        return self.descriptor.capabilities


def registered_connection(
    *,
    account_id: AccountId,
    connection_id: BrokerConnectionId,
    broker_id: str = BROKER_ID,
    enabled: bool = True,
) -> RegisteredConnection:
    """Build the connection a deployment would register for this process."""
    ref = BrokerConnectionRef(account_id, connection_id, broker_id, "NSE")
    return RegisteredConnection(ref, RegistryAdapter(ref), enabled=enabled)


def registry_with(registered: RegisteredConnection) -> AccountConnectionRegistry:
    registry = AccountConnectionRegistry()
    registry.register(registered)
    return registry


def catalog_for(
    source: LiveRiskEvidenceSource,
    *,
    broker_client_id: str,
    transport: object,
    broker_id: str = BROKER_ID,
) -> LiveRiskEvidenceSourceCatalog:
    """Register one construction path over ``source`` for one broker.

    This is the sanctioned test-side registration mechanism: the catalog owns
    the construction path, and the builder derives account and connection from
    the registry entry it is handed rather than from the source.
    """

    def build(registered: RegisteredConnection) -> TrustedLiveRiskEvidenceBinding:
        return TrustedLiveRiskEvidenceBinding(
            source=source,
            account_id=registered.ref.account_id,
            broker_connection_id=registered.ref.connection_id,
            broker_client_id=broker_client_id,
            transport=transport,
        )

    builder = LiveRiskEvidenceSourceBuilder(broker_id=broker_id, build=build)
    return LiveRiskEvidenceSourceCatalog(builders=(builder,))


def catalog_with_builder(build, *, broker_id: str = BROKER_ID) -> LiveRiskEvidenceSourceCatalog:
    """Register an arbitrary builder so a test can exercise rejection paths."""
    builder = LiveRiskEvidenceSourceBuilder(broker_id=broker_id, build=build)
    return LiveRiskEvidenceSourceCatalog(builders=(builder,))
