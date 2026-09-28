"""SQLite UnitOfWork binding repositories to one shared transaction."""

from __future__ import annotations

import contextlib
import sqlite3
from types import TracebackType

from quantx.persistence.unit_of_work import (
    PersistentIdempotencyStore,
    ReceiptRepository,
    UnitOfWork,
)

from .database import SqliteDatabase
from .idempotency import SqliteIdempotencyStore
from .receipts import SqliteReceiptRepository


class SqliteUnitOfWork(UnitOfWork):
    """Application transaction boundary over one shared SQLite connection.

    Nested transactions are rejected; savepoints belong to a later batch.
    """

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database
        self._idempotency = SqliteIdempotencyStore(database)
        self._receipts = SqliteReceiptRepository(database)
        self._active = False
        self._transaction: contextlib.AbstractContextManager[sqlite3.Connection] | None = None

    @property
    def idempotency(self) -> PersistentIdempotencyStore:
        return self._idempotency

    @property
    def receipts(self) -> ReceiptRepository:
        return self._receipts

    def commit(self) -> None:
        if not self._active:
            raise RuntimeError("no active UnitOfWork transaction to commit")
        self._database.connection().commit()

    def rollback(self) -> None:
        if not self._active:
            raise RuntimeError("no active UnitOfWork transaction to roll back")
        self._database.connection().rollback()

    def __enter__(self) -> UnitOfWork:
        if self._active:
            raise RuntimeError("nested UnitOfWork transactions are not supported")
        transaction = self._database.transaction()
        transaction.__enter__()
        self._transaction = transaction
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        transaction = self._transaction
        assert transaction is not None
        try:
            transaction.__exit__(exc_type, exc_value, traceback)
        finally:
            self._transaction = None
            self._active = False
