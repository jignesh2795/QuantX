"""SQLite adapter for durable trading-gate state."""

from __future__ import annotations

from datetime import UTC, datetime

from quantx.execution.trading_gate import TradingGateState, TradingGateStateStore

from .database import SqliteDatabase


class SqliteTradingGateStateStore(TradingGateStateStore):
    """Persist the singleton trading-gate state in SQLite."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def load(self) -> TradingGateState | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT enabled, reason FROM trading_gate_state WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            return None
        enabled, reason = row
        return TradingGateState(enabled=bool(enabled), reason=reason)

    def save(self, state: TradingGateState) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO trading_gate_state (singleton_id, enabled, reason, updated_at) "
                "VALUES (1, ?, ?, ?) "
                "ON CONFLICT(singleton_id) DO UPDATE SET "
                "enabled=excluded.enabled, reason=excluded.reason, updated_at=excluded.updated_at",
                (int(state.enabled), state.reason, datetime.now(UTC).isoformat()),
            )
