"""Explicit production-process composition for QuantX startup recovery.

This module is the process boundary: it owns the durable SQLite lifecycle and
builds the account/connection registry from explicit caller configuration.
Broker credentials and concrete adapter construction stay outside the
application/domain layers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

from quantx.integrations.account_registry import AccountConnectionRegistry
from quantx.persistence.sqlite import SqliteDatabase, SqliteUnitOfWork

from .evidence_refresh import DefinitiveEvidencePolicy, RefreshPolicy
from .pending_recovery import (
    FillProvider,
    LocalAccountProvider,
    LocalOrderProvider,
    LocalPositionProvider,
)
from .recovery_composition import RecoveryEvidenceFactory, build_application_runtime
from .runtime import ApplicationRuntime, ApplicationStartupResult

RegistryConfigurator = Callable[[AccountConnectionRegistry], None]


@dataclass(frozen=True, slots=True)
class ProductionRuntimeConfig:
    """Explicit inputs required to construct one QuantX process runtime."""

    database_path: str | Path
    configure_registry: RegistryConfigurator
    evidence_factory: RecoveryEvidenceFactory
    expected_broker_id: str | None = None
    local_order_provider: LocalOrderProvider | None = None
    local_position_provider: LocalPositionProvider | None = None
    local_account_provider: LocalAccountProvider | None = None
    fill_provider: FillProvider | None = None
    evidence_policy: DefinitiveEvidencePolicy | None = None
    refresh_policy: RefreshPolicy | None = None


@dataclass(slots=True)
class ProductionRuntime:
    """Own the process resources and one-shot recovery-backed startup."""

    database: SqliteDatabase
    unit_of_work: SqliteUnitOfWork
    registry: AccountConnectionRegistry
    application: ApplicationRuntime

    def start(self, *, checked_at: datetime | None = None) -> ApplicationStartupResult:
        """Run mandatory pending recovery before the process becomes ready."""
        return self.application.start(checked_at=checked_at)

    @property
    def started(self) -> bool:
        return self.application.started

    def close(self) -> None:
        """Close the process-owned durable database connection."""
        self.database.close()

    def __enter__(self) -> ProductionRuntime:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def build_production_runtime(config: ProductionRuntimeConfig) -> ProductionRuntime:
    """Build a complete recovery-backed process runtime from explicit inputs.

    The registry is populated only by the supplied configurator. No default
    account, connection, broker, credential, or adapter is selected here.
    """
    database = SqliteDatabase(config.database_path)
    unit_of_work = SqliteUnitOfWork(database)
    registry = AccountConnectionRegistry()
    try:
        config.configure_registry(registry)
        application = build_application_runtime(
            unit_of_work=unit_of_work,
            registry=registry,
            evidence_factory=config.evidence_factory,
            expected_broker_id=config.expected_broker_id,
            local_order_provider=config.local_order_provider,
            local_position_provider=config.local_position_provider,
            local_account_provider=config.local_account_provider,
            fill_provider=config.fill_provider,
            evidence_policy=config.evidence_policy,
            refresh_policy=config.refresh_policy,
        )
    except Exception:
        database.close()
        raise
    return ProductionRuntime(database, unit_of_work, registry, application)


__all__ = [
    "ProductionRuntime",
    "ProductionRuntimeConfig",
    "RegistryConfigurator",
    "build_production_runtime",
]
