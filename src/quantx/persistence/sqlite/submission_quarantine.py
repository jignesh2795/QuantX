"""SQLite-backed non-authoritative submission quarantine repository.

Rows are immutable and separate from the authoritative receipts table:
they never satisfy idempotency completion and are never returned as
canonical receipts. Writes are idempotent on ``observation_id`` — an
identical re-record is a no-op, a conflicting payload fails closed.
"""

from __future__ import annotations

import sqlite3
from uuid import UUID

from quantx.execution.receipts.quarantine import (
    MAX_SERIALIZED_PAYLOAD_CHARS,
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
    QuarantineEvidenceUnavailable,
)

from .database import SqliteDatabase

DEFAULT_MAX_SCAN_ROWS = 10_000
DEFAULT_MAX_PAYLOAD_CHARS = MAX_SERIALIZED_PAYLOAD_CHARS


def _sqlite_read_detail(error: sqlite3.Error) -> str:
    """Map a SQLite read failure to a static, operator-safe description.

    Driver messages can embed file paths and untrusted text, so they are never
    reproduced. The mapped detail distinguishes the common failure classes
    without exposing the raw exception.
    """
    if isinstance(error, sqlite3.OperationalError):
        return "the SQLite database is not readable in its current state"
    if isinstance(error, sqlite3.ProgrammingError):
        return "the SQLite evidence connection is not usable for reading"
    if isinstance(error, sqlite3.DatabaseError):
        return "the SQLite database file is corrupt or not a readable database"
    return "the SQLite driver could not complete the evidence read"


def _identity_key(value: object) -> tuple[str, str]:
    try:
        return ("uuid", str(UUID(str(value))))
    except (AttributeError, TypeError, ValueError):
        return ("text", str(value))


def _client_order_sql_key(value: object) -> str:
    """Canonical textual key for a client-order lookup.

    The writer stores a canonical UUID text for every UUID-parsable client
    order id, so a lookup must use the same canonical text rather than the
    caller's raw rendering. Genuinely opaque strings are not UUID-parsable
    and retain their raw textual form. This is a SQL scalar key, not the
    tuple-valued :func:`_identity_key` used for row identity comparison.
    """
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return str(value)


class SqliteSubmissionQuarantineRepository:
    """Durable quarantined-observation boundary; rows are immutable."""

    def __init__(
        self,
        database: SqliteDatabase,
        *,
        max_scan_rows: int = DEFAULT_MAX_SCAN_ROWS,
        max_payload_chars: int = DEFAULT_MAX_PAYLOAD_CHARS,
    ) -> None:
        if (
            isinstance(max_scan_rows, bool)
            or not isinstance(max_scan_rows, int)
            or max_scan_rows < 1
        ):
            raise ValueError("max_scan_rows must be a positive integer")
        if (
            isinstance(max_payload_chars, bool)
            or not isinstance(max_payload_chars, int)
            or max_payload_chars < 1
        ):
            raise ValueError("max_payload_chars must be a positive integer")
        self._database = database
        self._max_scan_rows = max_scan_rows
        self._max_payload_chars = max_payload_chars

    def record(self, observation: QuarantinedSubmissionObservation) -> None:
        """Persist one observation, or fail closed before any write.

        The serialized size is checked against the same canonical bound the
        reader uses. Every value produced by the validated constructor fits the
        bound, so this check is not reachable for a normal observation; it
        rejects a value whose runtime type lies about its serialized form (for
        example a ``str`` subclass overriding ``__str__``).

        The serialized payload is then decoded with the default reader's own
        contract before the insert, and the identity columns are derived from
        that decoded record. This closes the second half of the write/read
        invariant: a runtime type whose identity rendering changes between the
        payload and the column write can neither store a payload the reader
        refuses nor store columns that disagree with the payload. Rejecting
        such a value before the insert is deliberate: storing it would create a
        durable row no default reader can decode, silently losing the evidence.
        The caller treats a rejected record as a persistence failure and latches
        the existing fail-closed safety fault; it never stores an unreadable row.
        """
        payload = observation.to_payload()
        if len(payload) > MAX_SERIALIZED_PAYLOAD_CHARS:
            raise ValueError(
                "serialized quarantine observation exceeds the "
                f"{MAX_SERIALIZED_PAYLOAD_CHARS}-character write bound"
            )
        try:
            stored = QuarantinedSubmissionObservation.from_payload(payload)
        except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
            raise ValueError(
                "serialized quarantine observation is not decodable by the default reader"
            ) from exc
        observation_id_text = str(stored.observation_id)
        client_order_id_text = str(stored.client_order_id)
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM submission_quarantine WHERE observation_id = ?",
                (observation_id_text,),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError("cannot overwrite an existing quarantined observation")
                return
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    observation_id_text,
                    client_order_id_text,
                    payload,
                    stored.observed_at.isoformat(),
                ),
            )

    def _decode_row(
        self,
        observation_id: object,
        client_order_id: object,
        payload: str,
    ) -> QuarantinedSubmissionObservation:
        try:
            observation = QuarantinedSubmissionObservation.from_payload(payload)
        except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
            raise QuarantineEvidenceDecodeError(observation_id) from exc
        if _identity_key(observation.observation_id) != _identity_key(observation_id) or (
            _identity_key(observation.client_order_id) != _identity_key(client_order_id)
        ):
            raise QuarantineEvidenceDecodeError(
                observation_id,
                detail="stored row identity does not match the payload identity",
            )
        return observation

    def get(self, observation_id: UUID) -> QuarantinedSubmissionObservation | None:
        with self._database.read_transaction() as connection:
            row = connection.execute(
                "SELECT observation_id, client_order_id, payload "
                "FROM submission_quarantine WHERE observation_id = ?",
                (str(observation_id),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_row(row[0], row[1], row[2])

    def list_by_client_order(
        self, client_order_id: UUID | str
    ) -> tuple[QuarantinedSubmissionObservation, ...]:
        with self._database.read_transaction() as connection:
            rows = connection.execute(
                "SELECT observation_id, client_order_id, payload "
                "FROM submission_quarantine WHERE client_order_id = ? ORDER BY rowid",
                (_client_order_sql_key(client_order_id),),
            ).fetchall()
        return tuple(self._decode_row(row[0], row[1], row[2]) for row in rows)

    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        """Return durable observations in storage order; never mutates.

        The read is bounded: at most ``max_scan_rows`` rows and
        ``max_payload_chars`` characters per row are materialized. Exceeding
        either bound raises :class:`QuarantineEvidenceTooLarge`; evidence is
        never silently omitted or truncated. A payload that cannot be decoded,
        including a payload whose identity disagrees with its stored columns,
        raises :class:`QuarantineEvidenceDecodeError` carrying the affected row
        identity, so a corrupt record can never be mistaken for an empty
        worklist or silently dropped from an operator's view.

        ``max_payload_chars`` defaults to the canonical write bound, so every
        observation the write boundary accepted is readable. Raising the read
        bound is safe; lowering it below the write bound intentionally reports
        its own store as unreadable rather than admitting an over-bound row.

        SQLite failures are raised as :class:`QuarantineEvidenceUnavailable`
        with a static description; the driver message is never propagated.

        SQLite ``length``/``substr`` text semantics stop at an embedded NUL.
        Such a payload cannot be valid JSON (the writer escapes every control
        character), so it is reported as undecodable rather than readable.

        The query runs in a deferred read transaction, so it takes no writer
        lock and observes one consistent snapshot.
        """
        try:
            with self._database.read_transaction() as connection:
                rows = connection.execute(
                    "SELECT observation_id, client_order_id, length(payload), "
                    "substr(payload, 1, ?) FROM submission_quarantine "
                    "ORDER BY rowid LIMIT ?",
                    (self._max_payload_chars, self._max_scan_rows + 1),
                ).fetchall()
        except sqlite3.Error as exc:
            raise QuarantineEvidenceUnavailable(_sqlite_read_detail(exc)) from exc
        if len(rows) > self._max_scan_rows:
            raise QuarantineEvidenceTooLarge(
                f"row count exceeds the {self._max_scan_rows}-row scan bound"
            )
        observations: list[QuarantinedSubmissionObservation] = []
        for observation_id, client_order_id, payload_length, payload in rows:
            if payload_length > self._max_payload_chars:
                raise QuarantineEvidenceTooLarge(
                    f"payload exceeds the {self._max_payload_chars}-character bound",
                    observation_id=observation_id,
                )
            observations.append(self._decode_row(observation_id, client_order_id, payload))
        return tuple(observations)
