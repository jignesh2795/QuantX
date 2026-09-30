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
