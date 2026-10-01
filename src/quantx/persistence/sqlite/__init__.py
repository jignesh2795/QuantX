"""SQLite adapter implementing the database-neutral persistence contracts."""

from .database import SqliteDatabase
from .idempotency import SqliteIdempotencyStore
from .market_data import SqliteMarketDataStore
from .receipts import SqliteReceiptRepository, receipt_from_payload, receipt_to_payload
from .trading_gate import SqliteTradingGateStateStore
from .unit_of_work import SqliteUnitOfWork

__all__ = [
    "SqliteDatabase",
    "SqliteIdempotencyStore",
    "SqliteMarketDataStore",
    "SqliteReceiptRepository",
    "SqliteTradingGateStateStore",
    "SqliteUnitOfWork",
    "receipt_from_payload",
    "receipt_to_payload",
]
