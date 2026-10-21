"""Read-boundary tests for the SQLite submission-quarantine repository."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from quantx.execution.receipts.quarantine import (
    MAX_SERIALIZED_PAYLOAD_CHARS,
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
    QuarantineEvidenceUnavailable,
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


class _OversizedClientOrderId(str):
    def __str__(self) -> str:
        return "x" * (MAX_SERIALIZED_PAYLOAD_CHARS + 1)


class _AlternatingClientOrderId(str):
    calls = 0

    def __str__(self) -> str:
        type(self).calls += 1
        if type(self).calls % 2:
            return "short"
        return "x" * 40_000


class _OverlongClientOrderId(str):
    def __str__(self) -> str:
        return "x" * 300


def test_record_rejects_serialized_payload_over_shared_bound(tmp_path) -> None:
    observation = _observation(client_order_id=_OversizedClientOrderId("x"))
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        with pytest.raises(ValueError, match="serialized quarantine observation"):
            repository.record(observation)
        stored = (
            database.connection()
            .execute("SELECT COUNT(*) FROM submission_quarantine")
            .fetchone()[0]
        )

    assert stored == 0


def test_record_derives_identity_columns_from_the_serialized_payload(tmp_path) -> None:
    _AlternatingClientOrderId.calls = 0
    observation = _observation(client_order_id=_AlternatingClientOrderId("seed"))
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        listed = repository.list_all()
        row = (
            database.connection()
            .execute(
                "SELECT observation_id, client_order_id, length(payload) FROM submission_quarantine"
            )
            .fetchone()
        )

    # A type whose identity rendering changes between calls cannot store a row
    # whose columns disagree with the payload: the second rendering is never
    # used, and the stored record remains readable.
    assert len(listed) == 1
    assert listed[0].client_order_id == "short"
    assert row[1] == "short"
    assert row[2] <= MAX_SERIALIZED_PAYLOAD_CHARS


def test_record_rejects_a_payload_the_default_reader_would_refuse(tmp_path) -> None:
    observation = _observation(client_order_id=_OverlongClientOrderId("seed"))
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        with pytest.raises(ValueError, match="not decodable by the default reader"):
            repository.record(observation)
        stored = (
            database.connection()
            .execute("SELECT COUNT(*) FROM submission_quarantine")
            .fetchone()[0]
        )

    assert stored == 0


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


_MAXIMAL_TEXT = "\U0001f600" * 256
_MAXIMAL_REASON = "\U0001f600" * 512
# Widest legal ``datetime.isoformat`` result: 26 characters plus a 16-character
# UTC offset (``9999-12-31T23:59:59.999999+23:59:59.999999``).
_MAXIMAL_OBSERVED_AT = datetime(
    9999,
    12,
    31,
    23,
    59,
    59,
    999999,
    tzinfo=timezone(timedelta(hours=23, minutes=59, seconds=59, microseconds=999999)),
)


def _maximal_observation() -> QuarantinedSubmissionObservation:
    return QuarantinedSubmissionObservation(
        observation_id=uuid4(),
        kind=QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN,
        client_order_id=_MAXIMAL_TEXT,
        observed_at=_MAXIMAL_OBSERVED_AT,
        reason=_MAXIMAL_REASON,
        request_correlation_id=_MAXIMAL_TEXT,
        source=_MAXIMAL_TEXT,
        broker_order_id=_MAXIMAL_TEXT,
        outcome=_MAXIMAL_TEXT,
        order_status=_MAXIMAL_TEXT,
    )


def test_writer_accepts_and_reader_decodes_the_proven_worst_case_payload(tmp_path) -> None:
    observation = _maximal_observation()
    payload = observation.to_payload()

    # The shared bound is derived, not guessed: this observation touches every
    # field limit, the widest enum value, a maximal ISO timestamp, and the
    # widest JSON escaping (an astral code point costs twelve characters).
    assert len(payload) == MAX_SERIALIZED_PAYLOAD_CHARS

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        listed = repository.list_all()

    assert len(listed) == 1
    assert listed[0].to_payload() == payload


def test_default_scan_bound_is_exact_at_ten_thousand_rows(tmp_path) -> None:
    observations = tuple(_observation() for _ in range(10_000))
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        _insert_observations(database, observations)
        listed = repository.list_all()
        _insert_observations(database, (_observation(),))
        with pytest.raises(
            QuarantineEvidenceTooLarge,
            match="row count exceeds the 10000-row scan bound",
        ):
            repository.list_all()

    assert len(listed) == 10_000


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source", {"unexpected": "mapping"}),
        ("broker_order_id", 12345),
        ("outcome", ""),
        ("order_status", " UNKNOWN "),
        ("request_correlation_id", 3.5),
    ),
)
def test_list_all_rejects_non_canonical_stored_optional_field(
    tmp_path,
    field_name: str,
    value: object,
) -> None:
    observation = _observation()
    payload = json.loads(observation.to_payload())
    payload[field_name] = value
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        _insert_payload(
            database,
            str(observation.observation_id),
            str(observation.client_order_id),
            json.dumps(payload),
        )

        with pytest.raises(QuarantineEvidenceDecodeError) as raised:
            repository.list_all()

    assert str(observation.observation_id) in str(raised.value)


def test_list_all_ignores_unknown_stored_keys_without_surfacing_them(tmp_path) -> None:
    observation = _observation()
    payload = json.loads(observation.to_payload())
    payload["raw_response"] = {"secret": "tok-secret-value"}
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        _insert_payload(
            database,
            str(observation.observation_id),
            str(observation.client_order_id),
            json.dumps(payload),
        )
        listed = repository.list_all()

    assert listed == (observation,)
    assert "tok-secret-value" not in listed[0].to_payload()


def test_list_all_maps_driver_failure_to_static_unavailable(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        database.connection().close()
        repository = SqliteSubmissionQuarantineRepository(database)
        with pytest.raises(QuarantineEvidenceUnavailable) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(raised.value) == (
        "quarantine evidence store could not be read: "
        "the SQLite evidence connection is not usable for reading"
    )


def test_list_all_maps_missing_table_to_static_unavailable(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        repository = SqliteSubmissionQuarantineRepository(database)
        with database.transaction() as connection:
            connection.execute("DROP TABLE submission_quarantine")
        with pytest.raises(QuarantineEvidenceUnavailable) as raised:
            repository.list_all()
    finally:
        database.close()

    assert str(raised.value) == (
        "quarantine evidence store could not be read: "
        "the SQLite database is not readable in its current state"
    )


def _insert_observations(
    database: SqliteDatabase,
    observations: tuple[QuarantinedSubmissionObservation, ...],
) -> None:
    rows = [
        (
            str(observation.observation_id),
            str(observation.client_order_id),
            observation.to_payload(),
            observation.observed_at.isoformat(),
        )
        for observation in observations
    ]
    with database.transaction() as connection:
        connection.executemany(
            "INSERT INTO submission_quarantine "
            "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
            rows,
        )


def test_list_by_client_order_canonicalizes_uuid_write_and_uuid_lookup(tmp_path) -> None:
    client_order_id = uuid4()
    observation = _observation(client_order_id=client_order_id)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        found = repository.list_by_client_order(client_order_id)
    assert len(found) == 1
    assert found[0].observation_id == observation.observation_id


def test_list_by_client_order_uuid_parsable_string_write_and_same_string_lookup(tmp_path) -> None:
    client_text = str(uuid4()).upper()
    observation = _observation(client_order_id=client_text)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        found = repository.list_by_client_order(client_text)
    assert len(found) == 1
    assert found[0].observation_id == observation.observation_id
    assert str(found[0].client_order_id) == client_text.lower()


def test_list_by_client_order_uuid_parsable_string_write_and_canonical_lookup(tmp_path) -> None:
    client_text = str(uuid4()).upper()
    observation = _observation(client_order_id=client_text)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        found = repository.list_by_client_order(UUID(client_text))
    assert len(found) == 1
    assert found[0].observation_id == observation.observation_id


def test_list_by_client_order_handles_noncanonical_valid_uuid_text(tmp_path) -> None:
    base = uuid4()
    client_text = "{" + str(base) + "}"
    observation = _observation(client_order_id=client_text)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        assert len(repository.list_by_client_order(client_text)) == 1
        assert len(repository.list_by_client_order(UUID(client_text))) == 1
        assert len(repository.list_by_client_order(str(base).upper())) == 1


def test_list_by_client_order_preserves_opaque_string_lookup(tmp_path) -> None:
    client_text = "opaque-client-order-123"
    observation = _observation(client_order_id=client_text)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        found = repository.list_by_client_order(client_text)
        assert len(found) == 1
        assert found[0].observation_id == observation.observation_id
        assert repository.list_by_client_order("different-opaque-client") == ()


def test_list_by_client_order_preserves_insertion_order(tmp_path) -> None:
    client_text = "shared-opaque-client"
    first = _observation(client_order_id=client_text)
    second = _observation(client_order_id=client_text)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(first)
        repository.record(second)
        found = repository.list_by_client_order(client_text)
    assert [item.observation_id for item in found] == [first.observation_id, second.observation_id]


def test_list_by_client_order_fails_closed_on_corrupt_row(tmp_path) -> None:
    client_text = "opaque-client-order-456"
    observation = _observation(client_order_id="different-opaque-client")
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(_observation(client_order_id=client_text))
        _insert_payload(
            database,
            str(uuid4()),
            client_text,
            observation.to_payload(),
        )
        with pytest.raises(QuarantineEvidenceDecodeError):
            repository.list_by_client_order(client_text)


def test_list_by_client_order_reads_from_read_only_database(tmp_path) -> None:
    client_text = "opaque-client-order-789"
    observation = _observation(client_order_id=client_text)
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
    with SqliteDatabase.open_existing(path) as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        found = repository.list_by_client_order(client_text)
    assert len(found) == 1
    assert found[0].observation_id == observation.observation_id
