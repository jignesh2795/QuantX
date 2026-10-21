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
        SQLite is opened with the ``mode=ro`` URI flag, so the engine itself
        refuses every write — including a write attempted after
        ``PRAGMA query_only=OFF`` through the public connection handle.
        ``query_only`` and the write-transaction guard remain as defense in
        depth. The schema version must already be current; missing or
        unreadable tables are never repaired here, and reads fail closed until
        the database is repaired.

        Read-only is not side-effect free. A WAL-mode database is read through
        SQLite's WAL machinery, which may create or update ``-wal``/``-shm``
        companion files and may create an empty ``-wal`` for a cleanly closed
        database. A read-only connection cannot checkpoint, so a hot WAL is
        read where it stands rather than folded into the main file, and the
        main database file is not modified by a read. This is therefore not a
        byte-preserving inspection of the directory: preserve the only copy of
        evidence unopened and inspect a disposable copy taken after the last
        writer closed.
        """
        candidate = Path(path).absolute()
        if not candidate.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {path}")
        database = cls.__new__(cls)
        database._path = str(candidate)
        database._lock = RLock()
        database._read_only = True
        connection = sqlite3.connect(
            f"{candidate.as_uri()}?mode=ro",
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
    def path(self) -> str:
        """Absolute path this instance opened, for evidence-store verification."""
        if self._path == ":memory:":
            return self._path
        return str(Path(self._path).absolute())

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
