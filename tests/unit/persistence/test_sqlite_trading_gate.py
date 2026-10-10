"""SQLite durable trading-gate state tests."""

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
    import sqlite3

    import pytest

    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    store = SqliteTradingGateStateStore(database)
    gate = DurableTradingGate(store)
    database.close()

    with pytest.raises(sqlite3.ProgrammingError):
        gate.allow()
