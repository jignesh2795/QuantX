"""SQLite-backed non-authoritative submission quarantine repository.

Rows are immutable and separate from the authoritative receipts table:
they never satisfy idempotency completion and are never returned as
canonical receipts. Writes are idempotent on ``observation_id`` — an
identical re-record is a no-op, a conflicting payload fails closed.
"""

from __future__ import annotations

from uuid import UUID

from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
)

from .database import SqliteDatabase

DEFAULT_MAX_SCAN_ROWS = 10_000
DEFAULT_MAX_PAYLOAD_CHARS = 4_096


def _identity_key(value: object) -> tuple[str, str]:
    try:
        return ("uuid", str(UUID(str(value))))
    except (AttributeError, TypeError, ValueError):
        return ("text", str(value))


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
        payload = observation.to_payload()
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM submission_quarantine WHERE observation_id = ?",
                (str(observation.observation_id),),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError("cannot overwrite an existing quarantined observation")
                return
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation.observation_id),
                    str(observation.client_order_id),
                    payload,
                    observation.observed_at.isoformat(),
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
                (str(client_order_id),),
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

        The query runs in a deferred read transaction, so it takes no writer
        lock and observes one consistent snapshot.
        """
        with self._database.read_transaction() as connection:
            rows = connection.execute(
                "SELECT observation_id, client_order_id, length(payload), "
                "substr(payload, 1, ?) FROM submission_quarantine "
                "ORDER BY rowid LIMIT ?",
                (self._max_payload_chars, self._max_scan_rows + 1),
            ).fetchall()
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
