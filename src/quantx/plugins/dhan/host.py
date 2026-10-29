"""Dhan-specific production host/deployment adapter.

This module composes validated boundaries for one concrete deployment: Dhan
credentials/transport construction, exact account/connection registration,
read-only Dhan recovery evidence, and the existing one-shot
``ProductionRuntime`` startup lifecycle.

The host owns deployment concerns only. It performs no broker submission,
introduces no new execution semantics, persists no credentials, and creates
no background workers or daemons. Broker SDK types never cross into the
domain or application packages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

from quantx.application.evidence_refresh import DefinitiveEvidencePolicy, RefreshPolicy
from quantx.application.live_risk_sources import LiveRiskEvidenceSourceCatalog
from quantx.application.pending_recovery import (
    FillProvider,
    LocalAccountProvider,
    LocalOrderProvider,
    LocalPositionProvider,
)
from quantx.application.production import (
    ProductionRuntime,
    ProductionRuntimeConfig,
    build_production_runtime,
)
from quantx.application.runtime import ApplicationStartupResult
from quantx.domain.instruments import Instrument
from quantx.domain.policy_verification import MarketPackPolicyVerifier
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import AccountConnectionRegistry, RegisteredConnection
from quantx.integrations.brokers import BrokerConnectionRef

from .adapter import DhanBrokerAdapter
from .mapping import normalize_dhan_product_map
from .market_data import DhanMarketDataAdapter
from .models import DhanCredentials, DhanInstrumentRef
from .recovery import build_dhan_recovery_provider
from .risk_evidence import DhanRiskEvidenceSource
from .risk_evidence import build_dhan_risk_evidence_builder as _build_dhan_risk_evidence_builder
from .risk_evidence import build_dhan_risk_evidence_source as _build_dhan_risk_evidence_source
from .transport import DEFAULT_READ_TIMEOUT_SECONDS, DhanSDKTransport, DhanTransport

_DHAN_BROKER_ID = "dhan"


@dataclass(frozen=True, slots=True)
class DhanHostConfig:
    """Explicit inputs required to host one Dhan deployment process.

    Timeout values bound the caller's wait, never the vendor SDK call itself:
    a slow SDK call may still complete in the background after the timeout and
    its late result is discarded. The pinned vendor SDK (see the ``dhan`` extra
    in ``pyproject.toml``, currently version 2.2.0) enforces its own
    per-request HTTP timeout (``DhanHTTP.HTTP_DEFAULT_TIME_OUT = 60``) and
    surfaces SDK-side abandonment as a failure envelope, which the transport
    maps to UNKNOWN. A submit timeout above 60s is therefore safe but
    pointless: keep ``submit_timeout_seconds`` at or below 60 so the
    configured bound remains the operative one. Revisit this note only when
    the pinned SDK version changes.
    """

    database_path: str | Path
    account_id: AccountId
    connection_id: BrokerConnectionId
    market_context_id: str
    instruments: tuple[tuple[Instrument, DhanInstrumentRef], ...]
    submit_timeout_seconds: float
    cancel_timeout_seconds: float
    reconcile_timeout_seconds: float
    policy_verifier: MarketPackPolicyVerifier
    product_map: Mapping[str, str]
    read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    credentials: DhanCredentials | None = None
    transport: DhanTransport | None = None
    local_order_provider: LocalOrderProvider | None = None
    local_position_provider: LocalPositionProvider | None = None
    local_account_provider: LocalAccountProvider | None = None
    fill_provider: FillProvider | None = None
    evidence_policy: DefinitiveEvidencePolicy | None = None
    refresh_policy: RefreshPolicy | None = None

    def __post_init__(self) -> None:
        if isinstance(self.database_path, str) and not self.database_path.strip():
            raise ValueError("database path must not be empty")
        if not self.market_context_id.strip():
            raise ValueError("market context id must not be empty")
        if not self.instruments:
            raise ValueError("host instruments must not be empty")
        instrument_ids = [instrument.instrument_id for instrument, _ in self.instruments]
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("host instruments contain a duplicate instrument id")
        if (self.credentials is None) == (self.transport is None):
            raise ValueError("host requires exactly one of credentials or transport")
        try:
            product_map = normalize_dhan_product_map(self.product_map)
        except ValueError as exc:
            raise ValueError(f"invalid Dhan product map: {exc}") from exc
        object.__setattr__(self, "product_map", product_map)
        for name, value in (
            ("submit_timeout_seconds", self.submit_timeout_seconds),
            ("cancel_timeout_seconds", self.cancel_timeout_seconds),
            ("reconcile_timeout_seconds", self.reconcile_timeout_seconds),
            ("read_timeout_seconds", self.read_timeout_seconds),
        ):
            _validate_timeout_seconds(name, value)


@dataclass(frozen=True, slots=True)
class DhanHostRuntime:
    """Own a Dhan deployment process and its recovery-backed startup lifecycle."""

    config: DhanHostConfig
    transport: DhanTransport
    adapter: DhanBrokerAdapter
    market_data: DhanMarketDataAdapter
    runtime: ProductionRuntime

    @property
    def registry(self) -> AccountConnectionRegistry:
        """The exact account/connection registry backing startup recovery."""
        return self.runtime.registry

    def start(self, *, checked_at: datetime | None = None) -> ApplicationStartupResult:
        """Run mandatory pending recovery before the process becomes ready."""
        return self.runtime.start(checked_at=checked_at)

    @property
    def started(self) -> bool:
        return self.runtime.started

    def close(self) -> None:
        """Close process-owned persistence and transport deterministically.

        Transport shutdown is explicit host-owned lifecycle (the SDK
        transport's executor threads would otherwise leak); persistence is
        closed first so in-flight recovery work settles before the wire
        boundary is torn down. Transports without a ``close`` hook
        (pre-R0-B custom implementations) are tolerated.
        """
        try:
            self.runtime.close()
        finally:
            close = getattr(self.transport, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> DhanHostRuntime:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def build_dhan_host_runtime(config: DhanHostConfig) -> DhanHostRuntime:
    """Compose one Dhan host process from explicit deployment inputs.

    The registry is populated only from the supplied config. No default
    account, connection, broker, credential, or adapter is selected here.
    """
    transport = (
        config.transport
        if config.transport is not None
        else DhanSDKTransport(credentials=_require_credentials(config))
    )
    connection = BrokerConnectionRef(
        config.account_id,
        config.connection_id,
        _DHAN_BROKER_ID,
        config.market_context_id,
    )
    instrument_map = {
        instrument.instrument_id: (instrument, instrument_ref)
        for instrument, instrument_ref in config.instruments
    }
    adapter = DhanBrokerAdapter(
        _connection=connection,
        _instruments=instrument_map,
        _transport=transport,
        _submit_timeout=config.submit_timeout_seconds,
        _cancel_timeout=config.cancel_timeout_seconds,
        _reconcile_timeout=config.reconcile_timeout_seconds,
        _read_timeout=config.read_timeout_seconds,
        _product_map=config.product_map,
    )
    market_data = DhanMarketDataAdapter(_instruments=instrument_map, _transport=transport)

    def configure(registry: AccountConnectionRegistry) -> None:
        registry.register(RegisteredConnection(adapter.connection, adapter))

    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=config.database_path,
            configure_registry=configure,
            evidence_factory=build_dhan_recovery_provider,
            policy_verifier=config.policy_verifier,
            expected_broker_id=_DHAN_BROKER_ID,
            local_order_provider=config.local_order_provider,
            local_position_provider=config.local_position_provider,
            local_account_provider=config.local_account_provider,
            fill_provider=config.fill_provider,
            evidence_policy=config.evidence_policy,
            refresh_policy=config.refresh_policy,
        )
    )
    return DhanHostRuntime(
        config=config,
        transport=transport,
        adapter=adapter,
        market_data=market_data,
        runtime=runtime,
    )


def build_dhan_risk_evidence_source(
    host: DhanHostRuntime,
    *,
    broker_client_id: str | None = None,
) -> DhanRiskEvidenceSource:
    """Build the Dhan risk-evidence source over this host's exact transport.

    The source is bound to the host's configured account, connection, transport
    and read timeout. A host built from credentials already knows its broker
    client id; a host built over a custom transport must supply it explicitly.
    No default identity is invented. A bare source can be collected from, but it
    cannot reach LIVE admission: only the catalog-registered construction path
    in :func:`build_dhan_risk_evidence_catalog` issues the grant an authority
    consumes.
    """
    if type(host) is not DhanHostRuntime:
        raise TypeError("Dhan risk evidence host must be a DhanHostRuntime")
    return _build_dhan_risk_evidence_source(
        transport=host.transport,
        account_id=host.config.account_id,
        broker_connection_id=host.config.connection_id,
        broker_client_id=_dhan_broker_client_id(host, broker_client_id),
        instruments=host.config.instruments,
        read_timeout=host.config.read_timeout_seconds,
    )


def build_dhan_risk_evidence_catalog(
    host: DhanHostRuntime,
    *,
    broker_client_id: str | None = None,
) -> LiveRiskEvidenceSourceCatalog:
    """Compose the application-owned catalog that sanctions this host's Dhan source.

    The catalog registers exactly one construction path, keyed by the Dhan
    broker id, over the host's own transport, client id, instruments and read
    timeout. Registering it does not make Dhan authoritative: the source still
    declares daily P&L, equity and high-water mark unavailable, so sanctioned
    LIVE admission remains blocked before reservation and submission.
    """
    if type(host) is not DhanHostRuntime:
        raise TypeError("Dhan risk evidence host must be a DhanHostRuntime")
    builder = _build_dhan_risk_evidence_builder(
        transport=host.transport,
        broker_client_id=_dhan_broker_client_id(host, broker_client_id),
        instruments=host.config.instruments,
        read_timeout=host.config.read_timeout_seconds,
    )
    return LiveRiskEvidenceSourceCatalog(builders=(builder,))


def _dhan_broker_client_id(host: DhanHostRuntime, broker_client_id: str | None) -> str:
    """Derive the host's broker client id, never inventing a default."""
    client_id = broker_client_id
    if client_id is None:
        credentials = host.config.credentials
        if credentials is None:
            raise ValueError(
                "broker_client_id is required when the Dhan host uses a custom transport"
            )
        client_id = credentials.client_id
    if type(client_id) is not str or not client_id.strip():
        raise ValueError("Dhan risk evidence requires a non-empty broker client id")
    return client_id


def _validate_timeout_seconds(name: str, value: object) -> None:
    """Fail closed on non-numeric, bool, zero, or negative timeout config."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")


def _require_credentials(config: DhanHostConfig) -> DhanCredentials:
    if config.credentials is None:  # pragma: no cover - guarded by config validation
        raise ValueError("Dhan credentials are required when no transport is supplied")
    return config.credentials


__all__ = [
    "DhanHostConfig",
    "DhanHostRuntime",
    "build_dhan_host_runtime",
    "build_dhan_risk_evidence_catalog",
    "build_dhan_risk_evidence_source",
]
