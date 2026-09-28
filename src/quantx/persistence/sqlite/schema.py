"""SQLite schema version 1 for durable execution state."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

SCHEMA_VERSION = 1

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
    completed_at TEXT NULL
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


def init_schema(connection: sqlite3.Connection) -> None:
    """Create schema version 1 on first run; refuse incompatible versions."""
    connection.execute(_SCHEMA_TABLE)
    connection.execute(_IDEMPOTENCY_TABLE)
    connection.execute(_RECEIPTS_TABLE)
    connection.execute(_RECEIPTS_CLIENT_ORDER_INDEX)
    rows = connection.execute("SELECT version FROM schema_version").fetchall()
    if not rows:
        connection.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
    elif len(rows) != 1 or rows[0][0] != SCHEMA_VERSION:
        found = sorted(row[0] for row in rows)
        raise ValueError(f"incompatible SQLite schema version: found {found}")
    connection.commit()
