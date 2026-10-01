"""Schema lifecycle tests for the SQLite adapter."""

import sqlite3

import pytest

from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.schema import SCHEMA_VERSION


def test_schema_created_on_first_use(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        tables = {
            row[0]
            for row in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        database.close()
    assert {
        "schema_version",
        "idempotency_reservations",
        "receipts",
        "trading_gate_state",
    } <= tables


def test_schema_version_present(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        row = database.connection().execute("SELECT version FROM schema_version").fetchone()
    finally:
        database.close()
    assert row is not None
    assert row[0] == SCHEMA_VERSION


def test_reopen_existing_database(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    first = SqliteDatabase(path)
    first.close()
    second = SqliteDatabase(path)
    try:
        row = second.connection().execute("SELECT version FROM schema_version").fetchone()
    finally:
        second.close()
    assert row[0] == SCHEMA_VERSION


def test_incompatible_schema_version_rejected(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        raw.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION + 1, "test"),
        )
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(ValueError, match="incompatible"):
        SqliteDatabase(path)


def test_durability_pragmas_configured(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        connection = database.connection()
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        database.close()
    assert journal == "wal"
    assert synchronous == 2
    assert foreign_keys == 1


def test_v1_schema_is_migrated_to_current_version(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    raw = sqlite3.connect(str(path))
    try:
        raw.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at)
            VALUES (1, '2026-01-01T00:00:00+00:00');
            CREATE TABLE idempotency_reservations (
                client_order_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                receipt_id TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL
            );
            CREATE TABLE receipts (
                receipt_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        raw.commit()
    finally:
        raw.close()

    database = SqliteDatabase(path)
    try:
        columns = {
            row[1]
            for row in database.connection().execute(
                "PRAGMA table_info(idempotency_reservations)"
            ).fetchall()
        }
        tables = {
            row[0]
            for row in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = database.connection().execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
    finally:
        database.close()

    assert version == SCHEMA_VERSION
    assert "pending_context_json" in columns
    assert "trading_gate_state" in tables
