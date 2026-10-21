"""Single-connection SQLite database lifecycle for v0.1 persistence."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from threading import RLock
from types import TracebackType

from .schema import init_schema, require_current_schema


class SqliteDatabase:
    """Owns one shared SQLite connection for single-process, multi-thread use.

    All writes serialize on an RLock mirroring the in-memory store
    discipline. Durability target is WAL with synchronous=FULL. No
    pooling and no multi-process support in v0.1.

    ``open_existing`` creates a second, strictly read-only connection for
    inspection of an already-initialized database. It never creates or
    migrates a database. The primary constructor retains its initialize-on-open
    behavior.
    """

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self._path = str(path)
        self._lock = RLock()
        self._read_only = False
        self._connection = sqlite3.connect(self._path, check_same_thread=False, timeout=timeout)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        init_schema(self._connection)

    @classmethod
    def open_existing(cls, path: str | Path, *, timeout: float = 5.0) -> SqliteDatabase:
        """Open an existing database without creating or migrating it.

        Missing paths raise :class:`FileNotFoundError` and are never created.
        SQLite is opened with ``mode=rw`` (which refuses creation) and
        ``query_only`` as defense in depth, while the explicit write
        transaction guard rejects all writes. The schema must already be
        exactly current.
        """
        candidate = Path(path).absolute()
        if not candidate.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {path}")
        database = cls.__new__(cls)
        database._path = str(path)
        database._lock = RLock()
        database._read_only = True
        connection = sqlite3.connect(
            f"{candidate.as_uri()}?mode=rw",
            uri=True,
            check_same_thread=False,
            timeout=timeout,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            require_current_schema(connection)
        except BaseException:
            connection.close()
            raise
        database._connection = connection
        return database

    @property
    def lock(self) -> RLock:
        return self._lock

    def connection(self) -> sqlite3.Connection:
        return self._connection

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Join the ambient transaction or begin an outermost BEGIN IMMEDIATE."""
        with self._lock:
            if self._read_only:
                raise RuntimeError("a read-only database cannot open a write transaction")
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

    @contextlib.contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        """Read from one consistent snapshot without taking a write lock.

        The deferred ``BEGIN`` lets a WAL writer proceed while this reader
        holds its snapshot. The transaction always rolls back because this
        boundary is never used to persist work.
        """
        with self._lock:
            outermost = not self._connection.in_transaction
            if outermost:
                self._connection.execute("BEGIN")
            try:
                yield self._connection
            finally:
                if outermost:
                    self._connection.rollback()

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
