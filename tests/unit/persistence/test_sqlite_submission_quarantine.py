"""Read-boundary tests for the SQLite submission-quarantine repository."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
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


def _insert_payload(
    database: SqliteDatabase,
    observation_id: str,
    client_order_id: str,
    payload: str,
) -> None:
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO submission_quarantine "
            "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                observation_id,
                client_order_id,
                payload,
                datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
            ),
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


def test_list_all_rejects_payload_over_configured_bound(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database, max_payload_chars=100)
        observation = _observation()
        repository.record(observation)

        with pytest.raises(QuarantineEvidenceTooLarge, match="payload exceeds") as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(observation.observation_id) in str(raised.value)


def test_list_all_enforces_scan_bound_without_partial_results(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database, max_scan_rows=2)
        for _ in range(3):
            repository.record(_observation())

        with pytest.raises(QuarantineEvidenceTooLarge, match="row count exceeds"):
            repository.list_all()
    finally:
        database.close()


def test_list_all_accepts_exactly_the_scan_bound(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database, max_scan_rows=2)
        observations = (_observation(), _observation())
        for observation in observations:
            repository.record(observation)

        listed = repository.list_all()
    finally:
        database.close()

    assert [observation.observation_id for observation in listed] == [
        observation.observation_id for observation in observations
    ]


def test_list_all_reports_recursive_payload_with_row_identity(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        observation_id = uuid4()
        _insert_payload(
            database,
            str(observation_id),
            str(uuid4()),
            "[" * 2000 + "]" * 2000,
        )

        with pytest.raises(QuarantineEvidenceDecodeError) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(observation_id) in str(raised.value)


def test_list_all_rejects_payload_observation_identity_mismatch(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        payload_observation = _observation()
        row_observation_id = uuid4()
        _insert_payload(
            database,
            str(row_observation_id),
            str(payload_observation.client_order_id),
            payload_observation.to_payload(),
        )

        with pytest.raises(
            QuarantineEvidenceDecodeError,
            match="identity does not match",
        ) as raised:
            repository.list_all()
        with pytest.raises(
            QuarantineEvidenceDecodeError,
            match="identity does not match",
        ):
            repository.get(row_observation_id)
    finally:
        database.close()

    assert str(row_observation_id) in str(raised.value)


def test_list_all_rejects_payload_client_order_identity_mismatch(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        payload_observation = _observation()
        _insert_payload(
            database,
            str(payload_observation.observation_id),
            str(uuid4()),
            payload_observation.to_payload(),
        )

        with pytest.raises(
            QuarantineEvidenceDecodeError,
            match="identity does not match",
        ) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(payload_observation.observation_id) in str(raised.value)


def test_list_all_rejects_payload_missing_an_optional_key(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        observation = _observation()
        payload = json.loads(observation.to_payload())
        del payload["source"]
        _insert_payload(
            database,
            str(observation.observation_id),
            str(observation.client_order_id),
            json.dumps(payload),
        )

        with pytest.raises(QuarantineEvidenceDecodeError) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(observation.observation_id) in str(raised.value)


def test_repository_rejects_invalid_read_bounds() -> None:
    with pytest.raises(ValueError, match="max_scan_rows"):
        SqliteSubmissionQuarantineRepository(None, max_scan_rows=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_payload_chars"):
        SqliteSubmissionQuarantineRepository(None, max_payload_chars=True)  # type: ignore[arg-type]


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
