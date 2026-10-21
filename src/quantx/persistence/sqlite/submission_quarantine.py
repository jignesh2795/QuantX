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
)

from .database import SqliteDatabase


class SqliteSubmissionQuarantineRepository:
    """Durable quarantined-observation boundary; rows are immutable."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

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

    def get(self, observation_id: UUID) -> QuarantinedSubmissionObservation | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM submission_quarantine WHERE observation_id = ?",
                (str(observation_id),),
            ).fetchone()
        if row is None:
            return None
        return QuarantinedSubmissionObservation.from_payload(row[0])

    def list_by_client_order(
        self, client_order_id: UUID | str
    ) -> tuple[QuarantinedSubmissionObservation, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM submission_quarantine WHERE client_order_id = ? "
                "ORDER BY rowid",
                (str(client_order_id),),
            ).fetchall()
        return tuple(QuarantinedSubmissionObservation.from_payload(row[0]) for row in rows)

    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        """Return every durable observation in storage order; never mutates.

        A payload that cannot be decoded raises
        :class:`QuarantineEvidenceDecodeError` carrying the affected row
        identity, so a corrupt record can never be mistaken for an empty
        worklist or silently dropped from an operator's view. Structurally
        malformed payloads can fail with any of the decode exceptions below;
        ``AttributeError`` is included because ``UUID(<non-string>)`` raises
        it instead of a ``ValueError``.
        """
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT observation_id, payload FROM submission_quarantine ORDER BY rowid"
            ).fetchall()
        observations: list[QuarantinedSubmissionObservation] = []
        for observation_id, payload in rows:
            try:
                observations.append(QuarantinedSubmissionObservation.from_payload(payload))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise QuarantineEvidenceDecodeError(str(observation_id)) from exc
        return tuple(observations)
