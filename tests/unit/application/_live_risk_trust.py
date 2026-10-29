"""Shared factories for LIVE risk-evidence source-trust tests.

The registry adapter here only registers a connection; it never submits. Trust
is established the way a deployment establishes it: the adapter behind the
registered connection implements the application's evidence-provider protocol,
and the sanctioned factory derives its catalog from that adapter. A plain
registered connection therefore carries no evidence authority at all.
"""

from __future__ import annotations

from quantx.application.live_risk_evidence import LiveRiskEvidenceSource
from quantx.application.live_risk_sources import (
    LiveRiskEvidenceSourceCatalog,
    TrustedLiveRiskEvidenceBinding,
    live_risk_evidence_catalog_for,
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
DEFAULT_CLIENT = "client-1"

_DEFAULT_TRANSPORT = object()


class RegistryAdapter:
    """Minimal BrokerAdapter: registers a connection identity, nothing more.

    It deliberately exposes no evidence construction path, which is the default
    an ordinary registration has.
    """

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


class EvidenceAdapter(RegistryAdapter):
    """Registered adapter that owns its LIVE risk-evidence construction path."""

    def __init__(
        self,
        connection: BrokerConnectionRef,
        *,
        source: LiveRiskEvidenceSource | None = None,
        broker_client_id: str = DEFAULT_CLIENT,
        transport: object = _DEFAULT_TRANSPORT,
        binding: TrustedLiveRiskEvidenceBinding | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(connection)
        self._source = source
        self._broker_client_id = broker_client_id
        self._transport = transport
        self._binding = binding
        self._error = error
        self.binding_calls = 0

    def build_live_risk_evidence_binding(
        self, registered: RegisteredConnection
    ) -> TrustedLiveRiskEvidenceBinding | None:
        self.binding_calls += 1
        if self._error is not None:
            raise self._error
        if self._binding is not None:
            return self._binding
        assert self._source is not None
        return TrustedLiveRiskEvidenceBinding(
            source=self._source,
            account_id=registered.ref.account_id,
            broker_connection_id=registered.ref.connection_id,
            broker_client_id=self._broker_client_id,
            transport=self._transport,
        )


def registered_connection(
    *,
    account_id: AccountId,
    connection_id: BrokerConnectionId,
    broker_id: str = BROKER_ID,
    enabled: bool = True,
    source: LiveRiskEvidenceSource | None = None,
    broker_client_id: str = DEFAULT_CLIENT,
    transport: object = _DEFAULT_TRANSPORT,
    binding: TrustedLiveRiskEvidenceBinding | None = None,
    error: Exception | None = None,
) -> RegisteredConnection:
    """Build the connection a deployment would register for this process.

    Without ``source``/``binding``/``error`` the adapter exposes no evidence
    construction path, which is exactly what a plain broker registration is.
    """
    ref = BrokerConnectionRef(account_id, connection_id, broker_id, "NSE")
    if source is None and binding is None and error is None:
        return RegisteredConnection(ref, RegistryAdapter(ref), enabled=enabled)
    adapter = EvidenceAdapter(
        ref,
        source=source,
        broker_client_id=broker_client_id,
        transport=transport,
        binding=binding,
        error=error,
    )
    return RegisteredConnection(ref, adapter, enabled=enabled)


def registry_with(registered: RegisteredConnection) -> AccountConnectionRegistry:
    registry = AccountConnectionRegistry()
    registry.register(registered)
    return registry


def evidence_adapter(registered: RegisteredConnection) -> EvidenceAdapter:
    """Return the registered adapter as its evidence-providing form."""
    adapter = registered.adapter
    assert isinstance(adapter, EvidenceAdapter)
    return adapter


def catalog_for(registered: RegisteredConnection) -> LiveRiskEvidenceSourceCatalog:
    """Derive the application catalog for one registered connection.

    This is the only way a test can obtain a catalog, mirroring the sanctioned
    factory: the construction path is the registered adapter's own method.
    """
    catalog = live_risk_evidence_catalog_for(registered)
    assert catalog is not None
    return catalog
