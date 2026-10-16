"""SQLite adapter for durable trading-gate state."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from quantx.execution.trading_gate import TradingGateState, TradingGateStateStore

from .database import SqliteDatabase


class SqliteTradingGateStateStore(TradingGateStateStore):
    """Persist the singleton trading-gate state in SQLite."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    @property
    def shared_fault_domain(self) -> SqliteDatabase:
        """Scope process-local gate faults to the shared database.

        Separate store wrappers over one database share one fault domain, so
        a failed persist observed through any wrapper blocks every gate bound
        to that database. Independent databases never share faults.
        """
        return self._database

    def load(self) -> TradingGateState | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT enabled, reason FROM trading_gate_state WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            return None
        enabled, reason = row
        # A corrupt row must never decode into a permissive state. Gate query
        # paths treat a raised decode error as unavailable and fail closed.
        if enabled not in (0, 1) or not isinstance(reason, str):
            raise ValueError("corrupt trading-gate state row")
        return TradingGateState(enabled=bool(enabled), reason=reason)

    @contextmanager
    def synchronize(self) -> Iterator[None]:
        """Serialize gate submissions and state changes sharing this database."""
        with self._database.lock:
            yield

    def save(self, state: TradingGateState) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO trading_gate_state (singleton_id, enabled, reason, updated_at) "
                "VALUES (1, ?, ?, ?) "
                "ON CONFLICT(singleton_id) DO UPDATE SET "
                "enabled=excluded.enabled, reason=excluded.reason, updated_at=excluded.updated_at",
                (int(state.enabled), state.reason, datetime.now(UTC).isoformat()),
            )
