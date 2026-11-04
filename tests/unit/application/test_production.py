"""Tests for the explicit production-process runtime composition."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantx.application.production import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from quantx.domain.clock import FixedClock
from quantx.domain.value_objects import AccountId
from quantx.integrations.account_registry import AccountConnectionRegistry
from tests.unit._execution_request_proofs import policy_verifier


def test_build_production_runtime_uses_explicit_registry_configuration(tmp_path: Path) -> None:
    configured = []

    def configure_registry(registry: AccountConnectionRegistry) -> None:
        configured.append(registry)

    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=configure_registry,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=policy_verifier(),
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
            policy_verifier=policy_verifier(),
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


class CountingClock(FixedClock):
    def __init__(self, current: datetime) -> None:
        super().__init__(current)
        self.reads = 0

    def now(self) -> datetime:
        self.reads += 1
        return super().now()


def test_production_runtime_propagates_one_clock_read_through_startup(tmp_path: Path) -> None:
    instant = datetime(2026, 1, 1, 12, tzinfo=UTC)
    clock = CountingClock(instant)
    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=lambda registry: None,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=policy_verifier(),
            clock=clock,
        )
    )
    try:
        runtime.start()
        assert clock.reads == 1
        assert runtime.started
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
                policy_verifier=policy_verifier(),
            )
        )

    assert path.exists()


def test_build_production_runtime_database_close_failure_does_not_hide_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantx.persistence.sqlite import SqliteDatabase

    def close_boom(self: SqliteDatabase) -> None:
        raise RuntimeError("database close failed")

    monkeypatch.setattr(SqliteDatabase, "close", close_boom, raising=True)

    def fail(_: AccountConnectionRegistry) -> None:
        raise RuntimeError("registry configuration failed")

    with pytest.raises(RuntimeError, match="registry configuration failed") as exc_info:
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=tmp_path / "quantx.db",
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
                policy_verifier=policy_verifier(),
            )
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "database close failed"


def test_production_runtime_close_failure_is_surfaced(tmp_path: Path) -> None:
    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=lambda registry: None,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=policy_verifier(),
        )
    )

    def close_boom() -> None:
        raise RuntimeError("database close failed")

    runtime.database.close = close_boom

    with pytest.raises(RuntimeError, match="database close failed"):
        runtime.close()


def test_production_runtime_context_manager_preserves_body_exception_and_exposes_cleanup_failure(
    tmp_path: Path,
) -> None:
    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=lambda registry: None,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=policy_verifier(),
        )
    )

    def fail_close() -> None:
        raise RuntimeError("cleanup boom")

    runtime.database.close = fail_close

    with pytest.raises(RuntimeError, match="body") as exc_info:
        with runtime:
            raise RuntimeError("body")

    assert any("cleanup boom" in note for note in getattr(exc_info.value, "__notes__", []))


def test_production_runtime_cleanup_does_not_convert_keyboard_interrupt(tmp_path: Path) -> None:
    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=lambda registry: None,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=policy_verifier(),
        )
    )

    def fail_close() -> None:
        raise KeyboardInterrupt()

    runtime.database.close = fail_close

    with pytest.raises(KeyboardInterrupt):
        runtime.close()


def test_build_production_runtime_keyboard_interrupt_closes_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantx.persistence.sqlite import SqliteDatabase

    closed: list[int] = []

    def close_rec(self: SqliteDatabase) -> None:
        closed.append(1)
        SqliteDatabase.close.__wrapped__(self) if hasattr(
            SqliteDatabase.close, "__wrapped__"
        ) else None

    # Simpler: call original via unpatched reference captured before patching.
    original_close = SqliteDatabase.close

    def close_wrapper(self: SqliteDatabase) -> None:
        closed.append(1)
        original_close(self)

    monkeypatch.setattr(SqliteDatabase, "close", close_wrapper, raising=True)

    def fail(_: AccountConnectionRegistry) -> None:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=tmp_path / "quantx.db",
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
                policy_verifier=policy_verifier(),
            )
        )

    assert closed == [1]


def test_build_production_runtime_system_exit_closes_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantx.persistence.sqlite import SqliteDatabase

    closed: list[int] = []
    original_close = SqliteDatabase.close

    def close_wrapper(self: SqliteDatabase) -> None:
        closed.append(1)
        original_close(self)

    monkeypatch.setattr(SqliteDatabase, "close", close_wrapper, raising=True)

    def fail(_: AccountConnectionRegistry) -> None:
        raise SystemExit(7)

    with pytest.raises(SystemExit) as exc_info:
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=tmp_path / "quantx.db",
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
                policy_verifier=policy_verifier(),
            )
        )

    assert exc_info.value.code == 7
    assert closed == [1]


def test_build_production_runtime_interrupt_cleanup_failure_does_not_replace_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantx.persistence.sqlite import SqliteDatabase

    def close_boom(self: SqliteDatabase) -> None:
        raise RuntimeError("database close failed")

    monkeypatch.setattr(SqliteDatabase, "close", close_boom, raising=True)

    def fail(_: AccountConnectionRegistry) -> None:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt) as exc_info:
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=tmp_path / "quantx.db",
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
                policy_verifier=policy_verifier(),
            )
        )

    assert any("database close failed" in note for note in getattr(exc_info.value, "__notes__", []))


def test_build_production_runtime_interrupt_cleanup_interruption_does_not_replace_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantx.persistence.sqlite import SqliteDatabase

    def close_boom(self: SqliteDatabase) -> None:
        raise SystemExit(9)

    monkeypatch.setattr(SqliteDatabase, "close", close_boom, raising=True)

    def fail(_: AccountConnectionRegistry) -> None:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt) as exc_info:
        build_production_runtime(
            ProductionRuntimeConfig(
                database_path=tmp_path / "quantx.db",
                configure_registry=fail,
                evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
                policy_verifier=policy_verifier(),
            )
        )

    assert any(
        "SystemExit(9)" in note or "SystemExit" in note
        for note in getattr(exc_info.value, "__notes__", [])
    )
