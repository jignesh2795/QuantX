"""Single-connection SQLite database lifecycle for v0.1 persistence."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from threading import RLock
from types import TracebackType

from .schema import init_schema


class SqliteDatabase:
    """Owns one shared SQLite connection for single-process, multi-thread use.

    All writes serialize on an RLock mirroring the in-memory store
    discipline. Durability target is WAL with synchronous=FULL. No
    pooling and no multi-process support in v0.1.
    """

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self._path = str(path)
        self._lock = RLock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False, timeout=timeout)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        init_schema(self._connection)

    @property
    def lock(self) -> RLock:
        return self._lock

    def connection(self) -> sqlite3.Connection:
        return self._connection

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Join the ambient transaction or begin an outermost BEGIN IMMEDIATE."""
        with self._lock:
            outermost = not self._connection.in_transaction
            if outermost:
                self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                if outermost:
                    self._connection.rollback()
                raise
            else:
                if outermost:
                    self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SqliteDatabase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
