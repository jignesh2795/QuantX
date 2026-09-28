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
    assert {"schema_version", "idempotency_reservations", "receipts"} <= tables


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
