"""Read-boundary tests for the SQLite submission-quarantine repository."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineObservationKind,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteSubmissionQuarantineRepository


def _observation(
    *,
    kind: QuarantineObservationKind = QuarantineObservationKind.TRANSPORT_UNCERTAIN,
    observed_at: datetime | None = None,
    client_order_id=None,
    broker_order_id: str | None = "BR-1",
) -> QuarantinedSubmissionObservation:
    return QuarantinedSubmissionObservation(
        observation_id=uuid4(),
        kind=kind,
        client_order_id=client_order_id or uuid4(),
        observed_at=observed_at or datetime(2026, 1, 2, tzinfo=UTC),
        reason="transport outcome uncertain after submission may have begun; unresolved",
        request_correlation_id="correlation-1",
        source="dhan",
        broker_order_id=broker_order_id,
        outcome="UNKNOWN",
        order_status="UNKNOWN",
    )


def test_list_all_returns_every_recorded_observation(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        first = _observation(observed_at=datetime(2026, 1, 1, tzinfo=UTC))
        second = _observation(
            kind=QuarantineObservationKind.BROKER_UNKNOWN,
            observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        repository.record(first)
        repository.record(second)

        observations = repository.list_all()
    finally:
        database.close()

    assert [observation.observation_id for observation in observations] == [
        first.observation_id,
        second.observation_id,
    ]


def test_list_all_rejects_corrupt_payload_with_row_identity(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(_observation())
        observation_id = uuid4()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(uuid4()),
                    "{not-valid-json",
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )

        with pytest.raises(QuarantineEvidenceDecodeError) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(observation_id) in str(raised.value)


def test_list_all_rejects_structurally_malformed_payload_with_row_identity(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        observation_id = uuid4()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(uuid4()),
                    json.dumps(
                        {
                            "observation_id": {"not": "a uuid"},
                            "kind": "BROKER_UNKNOWN",
                            "client_order_id": str(uuid4()),
                            "observed_at": "2026-01-02T00:00:00+00:00",
                            "reason": "malformed evidence",
                        }
                    ),
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )

        with pytest.raises(QuarantineEvidenceDecodeError) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(observation_id) in str(raised.value)


def test_list_all_preserves_insertion_order_across_observation_timestamps(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        later = _observation(observed_at=datetime(2026, 1, 5, tzinfo=UTC))
        earlier = _observation(observed_at=datetime(2026, 1, 1, tzinfo=UTC))
        repository.record(later)
        repository.record(earlier)

        observations = repository.list_all()
    finally:
        database.close()

    # Storage order is insertion order; deterministic presentation ordering is
    # the read service's responsibility, not the adapter's.
    assert [observation.observation_id for observation in observations] == [
        later.observation_id,
        earlier.observation_id,
    ]


def test_list_all_does_not_mutate_evidence_rows(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(_observation(observed_at=datetime.now(UTC) - timedelta(days=1)))
        before = (
            database.connection()
            .execute("SELECT observation_id, payload FROM submission_quarantine ORDER BY rowid")
            .fetchall()
        )

        repository.list_all()
        repository.list_all()

        after = (
            database.connection()
            .execute("SELECT observation_id, payload FROM submission_quarantine ORDER BY rowid")
            .fetchall()
        )
    finally:
        database.close()

    assert after == before
