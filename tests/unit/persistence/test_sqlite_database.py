"""Read-only opening and read-transaction tests for the SQLite database."""

import sqlite3
from datetime import UTC, datetime

import pytest

from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.schema import SCHEMA_VERSION


def _insert_receipt(connection: sqlite3.Connection, receipt_id: str) -> None:
    connection.execute(
        "INSERT INTO receipts (receipt_id, client_order_id, payload, created_at) "
        "VALUES (?, ?, ?, ?)",
        (receipt_id, "client-1", "{}", datetime(2026, 1, 1, tzinfo=UTC).isoformat()),
    )


def _receipt_count(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]


def test_open_existing_missing_database_is_not_created(tmp_path) -> None:
    path = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        SqliteDatabase.open_existing(path)

    assert path.exists() is False


def test_open_existing_reads_without_creating_or_writing(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        with database.transaction() as connection:
            _insert_receipt(connection, "receipt-1")
    before = path.read_bytes()

    with SqliteDatabase.open_existing(path) as database:
        row = database.connection().execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == SCHEMA_VERSION
        assert _receipt_count(database.connection()) == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            database.connection().execute(
                "INSERT INTO receipts (receipt_id, client_order_id, payload, created_at) "
                "VALUES ('receipt-2', 'client-1', '{}', '2026-01-01T00:00:00+00:00')"
            )
        with pytest.raises(RuntimeError, match="read-only"):
            with database.transaction():
                pass

    assert path.read_bytes() == before


def test_open_existing_rejects_database_without_quantx_schema(tmp_path) -> None:
    path = tmp_path / "foreign.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(ValueError, match="no QuantX schema_version table"):
        SqliteDatabase.open_existing(path)

    raw = sqlite3.connect(path)
    try:
        tables = {
            row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        raw.close()
    assert tables == {"unrelated"}


def test_open_existing_rejects_non_current_schema_without_migrating(tmp_path) -> None:
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        raw.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION - 1, "test"),
        )
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(ValueError, match="incompatible"):
        SqliteDatabase.open_existing(path)

    raw = sqlite3.connect(path)
    try:
        row = raw.execute("SELECT version FROM schema_version").fetchone()
    finally:
        raw.close()
    assert row[0] == SCHEMA_VERSION - 1


def test_read_transaction_does_not_block_writer_and_holds_snapshot(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    writer = SqliteDatabase(path, timeout=0.2)
    try:
        with writer.transaction() as connection:
            _insert_receipt(connection, "receipt-1")

        reader = SqliteDatabase.open_existing(path)
        try:
            with reader.read_transaction() as connection:
                assert _receipt_count(connection) == 1
                with writer.transaction() as writer_connection:
                    _insert_receipt(writer_connection, "receipt-2")
                assert _receipt_count(connection) == 1

            assert _receipt_count(reader.connection()) == 2
        finally:
            reader.close()
    finally:
        writer.close()


def test_read_transaction_never_persists_a_write(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        with database.read_transaction() as connection:
            _insert_receipt(connection, "receipt-1")

        assert _receipt_count(database.connection()) == 0
