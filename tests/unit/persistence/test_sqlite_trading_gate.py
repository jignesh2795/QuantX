"""SQLite durable trading-gate state tests."""

import pytest

from quantx.execution.trading_gate import DurableTradingGate, TradingGateState
from quantx.persistence.sqlite import SqliteDatabase, SqliteTradingGateStateStore


def test_sqlite_trading_gate_state_survives_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database))
        gate.block("operator emergency stop")
        assert gate.allow() is False
    finally:
        database.close()

    reopened = SqliteDatabase(path)
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(reopened))
        assert gate.allow() is False
        assert gate.state() == TradingGateState(False, "operator emergency stop")
    finally:
        reopened.close()


def test_sqlite_trading_gate_enable_persists(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        store = SqliteTradingGateStateStore(database)
        gate = DurableTradingGate(store)
        gate.block("temporary halt")
        gate.enable()

    with SqliteDatabase(path) as reopened:
        restored = DurableTradingGate(SqliteTradingGateStateStore(reopened))
        assert restored.allow() is True
        assert restored.state() == TradingGateState(True, "")


def test_sqlite_gate_permit_fails_closed_when_state_row_missing(tmp_path) -> None:
    """A deleted gate-state row must refuse submissions, never approve them."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        store = SqliteTradingGateStateStore(database)
        gate = DurableTradingGate(store)
        store.save(TradingGateState(enabled=True, reason=""))

        with database.transaction() as connection:
            connection.execute("DELETE FROM trading_gate_state WHERE singleton_id = 1")

        with gate.submission_permit() as permitted:
            assert permitted is False
        assert gate.allow() is False
    finally:
        database.close()


def test_sqlite_gate_state_missing_after_reopen_reports_unavailable(tmp_path) -> None:
    """A reopened gate with no persisted row fails closed instead of approving."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        SqliteTradingGateStateStore(database)
    finally:
        database.close()

    reopened = SqliteDatabase(path)
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(reopened))
        reopened_state = SqliteTradingGateStateStore(reopened).load()

        if reopened_state is None:
            assert gate.allow() is False
        else:
            assert gate.allow() == reopened_state.enabled
    finally:
        reopened.close()


def test_sqlite_gate_closed_database_fails_closed(tmp_path) -> None:
    """An unreachable state store must fail closed: no approval is possible."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    store = SqliteTradingGateStateStore(database)
    gate = DurableTradingGate(store)
    database.close()

    assert gate.allow() is False
    assert gate.state() == TradingGateState(
        enabled=False,
        reason="durable trading-gate state is unavailable",
    )
    with gate.submission_permit() as permitted:
        assert permitted is False
    assert gate.admit_submission() is False


def test_sqlite_disarmed_default_survives_restart(tmp_path) -> None:
    """A successfully persisted disarmed default is still disarmed on reopen."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database))
        assert gate.allow() is False
    finally:
        database.close()

    reopened = SqliteDatabase(path)
    try:
        restored = DurableTradingGate(SqliteTradingGateStateStore(reopened))
        assert restored.allow() is False
        assert restored.state() == TradingGateState(enabled=False, reason="")
    finally:
        reopened.close()


def test_sqlite_gate_block_visible_to_existing_instance(tmp_path) -> None:
    """A successful block is observed by another live gate on the same store."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        first = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        second = DurableTradingGate(SqliteTradingGateStateStore(database))
        assert first.allow() is True

        first.block("operator emergency stop")

        assert second.allow() is False
        assert second.state() == TradingGateState(False, "operator emergency stop")
        with second.submission_permit() as permitted:
            assert permitted is False
    finally:
        database.close()


def test_sqlite_gate_corrupt_row_fails_closed(tmp_path) -> None:
    """A corrupt gate-state row must fail closed, never decode as enabled."""
    import sqlite3

    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        assert gate.allow() is True

        # The enabled column carries a CHECK (0, 1) constraint and TEXT
        # affinity coerces numbers to text, so corrupt with a BLOB reason,
        # which SQLite stores verbatim outside the TEXT domain.
        with database.transaction() as connection:
            connection.execute(
                "UPDATE trading_gate_state SET reason = ? WHERE singleton_id = 1",
                (sqlite3.Binary(b"corrupt"),),
            )

        assert gate.allow() is False
        assert gate.state() == TradingGateState(
            enabled=False,
            reason="durable trading-gate state is unavailable",
        )
        with gate.submission_permit() as permitted:
            assert permitted is False
        assert gate.admit_submission() is False
    finally:
        database.close()


class _FailDisableSqliteStore(SqliteTradingGateStateStore):
    """SQLite store wrapper whose disabled-state writes fail."""

    def save(self, state: TradingGateState) -> None:
        if not state.enabled:
            raise OSError("cannot persist disabled gate state")
        super().save(state)


class _FailEnableSqliteStore(SqliteTradingGateStateStore):
    """SQLite store wrapper whose enabled-state writes fail."""

    def save(self, state: TradingGateState) -> None:
        if state.enabled:
            raise OSError("cannot persist enabled gate state")
        super().save(state)


def _assert_gate_denied(gate: DurableTradingGate, reason: str) -> None:
    assert gate.allow() is False
    assert gate.state() == TradingGateState(False, reason)
    with gate.submission_permit() as permitted:
        assert permitted is False
    assert gate.admit_submission() is False


def test_sqlite_wrappers_sharing_database_deny_both_gates_on_failed_block(tmp_path) -> None:
    """Separate store wrappers over one database share one fault domain: a
    failed block through one wrapper denies every gate on that database,
    and a successful persist through the other wrapper recovers both."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        first = DurableTradingGate(_FailDisableSqliteStore(database), default_enabled=True)
        second = DurableTradingGate(SqliteTradingGateStateStore(database))
        assert first.allow() is True
        assert second.allow() is True

        with pytest.raises(OSError, match="cannot persist disabled gate state"):
            first.block("operator emergency stop")

        _assert_gate_denied(first, "operator emergency stop")
        _assert_gate_denied(second, "operator emergency stop")

        second.block("confirmed stop")
        _assert_gate_denied(first, "confirmed stop")
        _assert_gate_denied(second, "confirmed stop")
        assert SqliteTradingGateStateStore(database).load() == TradingGateState(
            False, "confirmed stop"
        )
    finally:
        database.close()


def test_sqlite_wrappers_sharing_database_failed_enable_recovers_on_success(tmp_path) -> None:
    """A failed enable through one wrapper denies both gates until the other
    wrapper persists an enable successfully; recovery happens only then."""
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        first = DurableTradingGate(_FailEnableSqliteStore(database))
        second = DurableTradingGate(SqliteTradingGateStateStore(database))
        second.enable()
        assert first.allow() is True
        assert second.allow() is True

        with pytest.raises(OSError, match="cannot persist enabled gate state"):
            first.enable()

        _assert_gate_denied(first, "durable trading-gate enable failed to persist")
        _assert_gate_denied(second, "durable trading-gate enable failed to persist")

        assert second.enable() == TradingGateState(enabled=True, reason="")
        assert first.allow() is True
        assert second.allow() is True
    finally:
        database.close()


def test_sqlite_independent_databases_do_not_share_faults(tmp_path) -> None:
    """A fault latched on one database must never affect another database."""
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"
    first_database = SqliteDatabase(first_path)
    second_database = SqliteDatabase(second_path)
    try:
        first = DurableTradingGate(_FailDisableSqliteStore(first_database), default_enabled=True)
        second = DurableTradingGate(
            SqliteTradingGateStateStore(second_database), default_enabled=True
        )
        assert first.allow() is True
        assert second.allow() is True

        with pytest.raises(OSError, match="cannot persist disabled gate state"):
            first.block("operator emergency stop")

        _assert_gate_denied(first, "operator emergency stop")
        assert second.allow() is True
        with second.submission_permit() as permitted:
            assert permitted is True
        assert second.admit_submission() is True
    finally:
        first_database.close()
        second_database.close()
