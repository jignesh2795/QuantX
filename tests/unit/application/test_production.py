"""Tests for the explicit production-process runtime composition."""

from pathlib import Path

import pytest

from quantx.application.production import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from quantx.domain.value_objects import AccountId
from quantx.integrations.account_registry import AccountConnectionRegistry


def test_build_production_runtime_uses_explicit_registry_configuration(tmp_path: Path) -> None:
    configured = []

    def configure_registry(registry: AccountConnectionRegistry) -> None:
        configured.append(registry)

    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=configure_registry,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
        )
    )
    try:
        assert runtime.registry is configured[0]
        assert runtime.registry.for_account(AccountId("acct-1")) == ()
        assert not runtime.started
    finally:
        runtime.close()


def test_production_runtime_start_runs_recovery_before_ready(tmp_path: Path) -> None:
    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=lambda registry: None,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
        )
    )
    try:
        result = runtime.start()
        assert runtime.started
        assert result.recovered == 0
        assert result.pending == 0
        assert result.failed == 0
    finally:
        runtime.close()


def test_registry_configuration_failure_closes_database(tmp_path: Path) -> None:
    path = tmp_path / "quantx.db"

    def fail(_: AccountConnectionRegistry) -> None:
        raise RuntimeError("registry configuration failed")

    with pytest.raises(RuntimeError, match="registry configuration failed"):
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=path,
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            )
        )

    assert path.exists()
