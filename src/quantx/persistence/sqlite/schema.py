"""SQLite schema lifecycle for durable execution state."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

SCHEMA_VERSION = 3

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""

_IDEMPOTENCY_TABLE = """
CREATE TABLE IF NOT EXISTS idempotency_reservations (
    client_order_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    receipt_id TEXT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NULL,
    pending_context_json TEXT NULL
)
"""

_RECEIPTS_TABLE = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_RECEIPTS_CLIENT_ORDER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_receipts_client_order
ON receipts (client_order_id)
"""

_TRADING_GATE_TABLE = """
CREATE TABLE IF NOT EXISTS trading_gate_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_MARKET_CANDLES_TABLE = """
CREATE TABLE IF NOT EXISTS market_candles (
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
)
"""

_MARKET_CANDLES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_market_candles_lookup
ON market_candles (instrument_venue, instrument_symbol, timeframe, timestamp)
"""

_MARKET_QUOTES_TABLE = """
CREATE TABLE IF NOT EXISTS market_quotes (
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
)
"""

_MARKET_QUOTES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_market_quotes_lookup
ON market_quotes (instrument_venue, instrument_symbol, timestamp)
"""


def _create_market_tables(connection: sqlite3.Connection) -> None:
    connection.execute(_MARKET_CANDLES_TABLE)
    connection.execute(_MARKET_CANDLES_INDEX)
    connection.execute(_MARKET_QUOTES_TABLE)
    connection.execute(_MARKET_QUOTES_INDEX)


def _create_current_schema(connection: sqlite3.Connection) -> None:
    connection.execute(_IDEMPOTENCY_TABLE)
    connection.execute(_RECEIPTS_TABLE)
    connection.execute(_RECEIPTS_CLIENT_ORDER_INDEX)
    connection.execute(_TRADING_GATE_TABLE)
    _create_market_tables(connection)


def init_schema(connection: sqlite3.Connection) -> None:
    """Create or migrate the durable execution schema to the current version."""
    connection.execute(_SCHEMA_TABLE)
    rows = connection.execute(
        "SELECT version FROM schema_version ORDER BY version"
    ).fetchall()

    if not rows:
        _create_current_schema(connection)
        connection.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        return

    if len(rows) != 1:
        found = sorted(row[0] for row in rows)
        raise ValueError(f"incompatible SQLite schema version: found {found}")

    version = rows[0][0]
    if version == 1:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(idempotency_reservations)"
            ).fetchall()
        }
        if "pending_context_json" not in columns:
            connection.execute(
                "ALTER TABLE idempotency_reservations "
                "ADD COLUMN pending_context_json TEXT NULL"
            )
        connection.execute(_TRADING_GATE_TABLE)
        _create_market_tables(connection)
        connection.execute(
            "UPDATE schema_version SET version = ?, applied_at = ? WHERE version = 1",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        return

    if version == 2:
        _create_market_tables(connection)
        connection.execute(
            "UPDATE schema_version SET version = ?, applied_at = ? WHERE version = 2",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        connection.commit()
        return

    if version != SCHEMA_VERSION:
        raise ValueError(f"incompatible SQLite schema version: found {[version]}")

    _create_current_schema(connection)
    connection.commit()
