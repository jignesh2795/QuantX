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
        "research_runs",
        "research_results",
        "research_manifests",
        "research_run_manifests",
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
        version = database.connection().execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        database.close()

    assert version == SCHEMA_VERSION
    assert "pending_context_json" in columns
    assert "trading_gate_state" in tables


def test_v2_schema_is_migrated_to_current_version(tmp_path) -> None:
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
            VALUES (2, '2026-01-01T00:00:00+00:00');
            CREATE TABLE idempotency_reservations (
                client_order_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                receipt_id TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL,
                pending_context_json TEXT NULL
            );
            INSERT INTO idempotency_reservations (
                client_order_id, fingerprint, receipt_id, created_at,
                completed_at, pending_context_json
            ) VALUES ('order-1', 'fp', NULL, '2026-01-01T00:00:00+00:00', NULL, NULL);
            CREATE TABLE receipts (
                receipt_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE trading_gate_state (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                reason TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        raw.commit()
    finally:
        raw.close()

    database = SqliteDatabase(path)
    try:
        tables = {
            row[0]
            for row in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = database.connection().execute("SELECT version FROM schema_version").fetchone()[0]
        preserved = database.connection().execute(
            "SELECT fingerprint FROM idempotency_reservations WHERE client_order_id = 'order-1'"
        ).fetchone()
    finally:
        database.close()

    assert version == SCHEMA_VERSION
    assert "market_candles" in tables
    assert "market_quotes" in tables
    assert preserved is not None
    assert preserved[0] == "fp"


def test_v4_schema_is_migrated_to_current_version(tmp_path) -> None:
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
            VALUES (4, '2026-01-01T00:00:00+00:00');
            CREATE TABLE idempotency_reservations (
                client_order_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                receipt_id TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL,
                pending_context_json TEXT NULL
            );
            CREATE TABLE receipts (
                receipt_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE operator_resolutions (
                client_order_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                action TEXT NOT NULL,
                evidence_reference TEXT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE trading_gate_state (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                reason TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE market_candles (
                instrument_venue TEXT NOT NULL,
                instrument_symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open TEXT NOT NULL,
                high TEXT NOT NULL,
                low TEXT NOT NULL,
                close TEXT NOT NULL,
                volume TEXT NOT NULL,
                source_id TEXT NOT NULL,
                dataset_version TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (
                    instrument_venue,
                    instrument_symbol,
                    timeframe,
                    timestamp,
                    source_id,
                    dataset_version
                )
            );
            CREATE TABLE market_quotes (
                instrument_venue TEXT NOT NULL,
                instrument_symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                bid TEXT NULL,
                ask TEXT NULL,
                last TEXT NULL,
                bid_size TEXT NULL,
                ask_size TEXT NULL,
                source_id TEXT NOT NULL,
                dataset_version TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (
                    instrument_venue,
                    instrument_symbol,
                    timestamp,
                    source_id,
                    dataset_version
                )
            );
            """
        )
        raw.commit()
    finally:
        raw.close()

    database = SqliteDatabase(path)
    try:
        version = database.connection().execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in database.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        database.close()

    assert version == SCHEMA_VERSION
    assert {
        "research_runs",
        "research_results",
        "research_manifests",
        "research_run_manifests",
    } <= tables
