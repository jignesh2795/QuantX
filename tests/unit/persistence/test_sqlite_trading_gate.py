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
