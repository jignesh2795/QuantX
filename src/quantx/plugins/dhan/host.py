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

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

from quantx.application.evidence_refresh import DefinitiveEvidencePolicy, RefreshPolicy
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
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import AccountConnectionRegistry, RegisteredConnection
from quantx.integrations.brokers import BrokerConnectionRef

from .adapter import DhanBrokerAdapter
from .models import DhanCredentials, DhanInstrumentRef
from .recovery import build_dhan_recovery_provider
from .transport import DhanSDKTransport, DhanTransport

_DHAN_BROKER_ID = "dhan"


@dataclass(frozen=True, slots=True)
class DhanHostConfig:
    """Explicit inputs required to host one Dhan deployment process."""

    database_path: str | Path
    account_id: AccountId
    connection_id: BrokerConnectionId
    market_context_id: str
    instruments: tuple[tuple[Instrument, DhanInstrumentRef], ...]
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


@dataclass(frozen=True, slots=True)
class DhanHostRuntime:
    """Own a Dhan deployment process and its recovery-backed startup lifecycle."""

    config: DhanHostConfig
    transport: DhanTransport
    adapter: DhanBrokerAdapter
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
        """Close process-owned persistence deterministically."""
        self.runtime.close()

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
    adapter = DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            instrument.instrument_id: (instrument, instrument_ref)
            for instrument, instrument_ref in config.instruments
        },
        _transport=transport,
    )

    def configure(registry: AccountConnectionRegistry) -> None:
        registry.register(RegisteredConnection(adapter.connection, adapter))

    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=config.database_path,
            configure_registry=configure,
            evidence_factory=build_dhan_recovery_provider,
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
        runtime=runtime,
    )


def _require_credentials(config: DhanHostConfig) -> DhanCredentials:
    if config.credentials is None:  # pragma: no cover - guarded by config validation
        raise ValueError("Dhan credentials are required when no transport is supplied")
    return config.credentials


__all__ = [
    "DhanHostConfig",
    "DhanHostRuntime",
    "build_dhan_host_runtime",
]
