"""Read-only worklist tests for durable quarantined submission evidence."""

import ast
import base64
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quantx.application.quarantine_worklist import (
    QuarantineEvidenceState,
    QuarantineWorklist,
    QuarantineWorklistReadService,
    QuarantineWorklistStatus,
    render_quarantine_worklist_item,
)
from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceTooLarge,
    QuarantineObservationKind,
)
from quantx.execution.trading_gate import DurableTradingGate
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteIdempotencyStore,
    SqliteReceiptRepository,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
)


def _observation(
    *,
    observation_id=None,
    kind: QuarantineObservationKind = QuarantineObservationKind.TRANSPORT_UNCERTAIN,
    observed_at: datetime | None = None,
    client_order_id=None,
    broker_order_id: str | None = "BR-1",
    source: str | None = "dhan",
    reason: str = "broker returned an UNKNOWN receipt; unresolved pending reconciliation",
    request_correlation_id: str | None = "correlation-keep-me",
    outcome: str | None = "UNKNOWN",
    order_status: str | None = "UNKNOWN",
) -> QuarantinedSubmissionObservation:
    return QuarantinedSubmissionObservation(
        observation_id=observation_id or uuid4(),
        kind=kind,
        client_order_id=client_order_id or uuid4(),
        observed_at=observed_at or datetime(2026, 1, 2, tzinfo=UTC),
        reason=reason,
        request_correlation_id=request_correlation_id,
        source=source,
        broker_order_id=broker_order_id,
        outcome=outcome,
        order_status=order_status,
    )


class _StrictReadOnlyQuarantinePort:
    """Port double that fails if the service uses anything but the read method."""

    def __init__(self, observations: tuple[QuarantinedSubmissionObservation, ...]) -> None:
        self._observations = observations
        self.list_calls = 0

    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        self.list_calls += 1
        return self._observations

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"worklist must not use quarantine port member {name!r}")


class _FailingQuarantinePort:
    """Port double whose durable read fails closed."""

    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        raise OSError("quarantine store unavailable")


class _ScriptedQuarantinePort:
    """Port double returning an arbitrary result for contract validation."""

    def __init__(self, result: object) -> None:
        self._result = result

    def list_all(self) -> object:
        return self._result


class _RaisingQuarantinePort:
    """Port double raising one configured exception."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        raise self._error


def _durable_snapshot(database: SqliteDatabase) -> dict[str, object]:
    connection = database.connection()
    return {
        "quarantine": connection.execute(
            "SELECT observation_id, payload FROM submission_quarantine ORDER BY rowid"
        ).fetchall(),
        "reservations": connection.execute(
            "SELECT client_order_id, fingerprint, receipt_id, pending_context_json, completed_at "
            "FROM idempotency_reservations ORDER BY client_order_id"
        ).fetchall(),
        "receipts": connection.execute(
            "SELECT receipt_id, payload FROM receipts ORDER BY receipt_id"
        ).fetchall(),
        "gate": connection.execute("SELECT enabled, reason FROM trading_gate_state").fetchall(),
        "not_submitted": connection.execute(
            "SELECT client_order_id FROM not_submitted_resolutions ORDER BY client_order_id"
        ).fetchall(),
        "operator": connection.execute(
            "SELECT client_order_id FROM operator_resolutions ORDER BY client_order_id"
        ).fetchall(),
    }


def test_worklist_lists_evidence_after_store_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    observation = _observation()
    database = SqliteDatabase(path)
    try:
        SqliteSubmissionQuarantineRepository(database).record(observation)
    finally:
        database.close()

    reopened = SqliteDatabase.open_existing(path)
    try:
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(reopened)
        ).read()
    finally:
        reopened.close()

    assert worklist.status is QuarantineWorklistStatus.OK
    assert len(worklist.items) == 1
    item = worklist.items[0]
    assert item.state is QuarantineEvidenceState.UNRESOLVED
    assert item.observation.observation_id == observation.observation_id
    assert item.observation.client_order_id == observation.client_order_id
    assert item.observation.kind is QuarantineObservationKind.TRANSPORT_UNCERTAIN


def test_worklist_orders_items_by_timestamp_then_observation_id() -> None:
    late = _observation(
        observation_id=UUID("00000000-0000-0000-0000-000000000003"),
        kind=QuarantineObservationKind.MALFORMED_RECEIPT,
        observed_at=datetime(2026, 1, 3, tzinfo=UTC),
        source="dhan",
    )
    early_b = _observation(
        observation_id=UUID("00000000-0000-0000-0000-000000000002"),
        kind=QuarantineObservationKind.BROKER_UNKNOWN,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="fake-broker",
    )
    early_a = _observation(
        observation_id=UUID("00000000-0000-0000-0000-000000000001"),
        kind=QuarantineObservationKind.IDENTITY_REJECTED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="dhan",
    )
    port = _StrictReadOnlyQuarantinePort((late, early_b, early_a))

    first = QuarantineWorklistReadService(quarantine=port).read()
    second = QuarantineWorklistReadService(quarantine=port).read()

    assert [item.observation.observation_id for item in first.items] == [
        early_a.observation_id,
        early_b.observation_id,
        late.observation_id,
    ]
    assert first == second
    assert port.list_calls == 2


def test_worklist_orders_by_instant_not_iso_text_across_offsets() -> None:
    earlier = _observation(
        observation_id=UUID("00000000-0000-0000-0000-000000000002"),
        observed_at=datetime(
            2026,
            1,
            1,
            14,
            30,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        ),
    )
    later = _observation(
        observation_id=UUID("00000000-0000-0000-0000-000000000001"),
        observed_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
    )
    service = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort((later, earlier))
    )

    worklist = service.read()

    assert [item.observation.observation_id for item in worklist.items] == [
        earlier.observation_id,
        later.observation_id,
    ]


def test_worklist_tolerates_missing_and_malformed_optional_metadata(tmp_path) -> None:
    observation_id = uuid4()
    client_order_id = uuid4()
    payload = json.dumps(
        {
            "observation_id": str(observation_id),
            "kind": "BROKER_UNKNOWN",
            "client_order_id": str(client_order_id),
            "observed_at": "2026-01-02T00:00:00+00:00",
            "reason": "broker returned an UNKNOWN receipt; unresolved pending reconciliation",
            "request_correlation_id": "correlation-keep-me",
            "source": {"unexpected": "mapping"},
            "broker_order_id": 12345,
            "outcome": "UNKNOWN",
            "order_status": "UNKNOWN",
        }
    )
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(client_order_id),
                    payload,
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert worklist.status is QuarantineWorklistStatus.OK
    assert len(worklist.items) == 1
    observation = worklist.items[0].observation
    assert observation.observation_id == observation_id
    assert observation.client_order_id == client_order_id
    assert observation.request_correlation_id == "correlation-keep-me"
    assert observation.broker_order_id is None
    assert observation.source is None


def test_repeated_read_leaves_durable_state_unchanged(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        client_order_id = uuid4()
        idempotency = SqliteIdempotencyStore(database)
        idempotency.reserve_or_get(client_order_id, "fingerprint-1")
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(_observation(client_order_id=client_order_id))
        gate = DurableTradingGate(SqliteTradingGateStateStore(database), default_enabled=True)
        assert gate.allow() is True
        before = _durable_snapshot(database)

        service = QuarantineWorklistReadService(quarantine=repository)
        first = service.read()
        second = service.read()

        after = _durable_snapshot(database)
    finally:
        database.close()

    assert first == second
    assert after == before


def test_worklist_evidence_stays_non_authoritative_and_pending(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        client_order_id = uuid4()
        idempotency = SqliteIdempotencyStore(database)
        idempotency.reserve_or_get(client_order_id, "fingerprint-1")
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(_observation(client_order_id=client_order_id))

        worklist = QuarantineWorklistReadService(quarantine=repository).read()

        decision = idempotency.check(client_order_id, "fingerprint-1")
        receipts = SqliteReceiptRepository(database)
        persisted_receipt = receipts.get_by_client_order(client_order_id)
        correlated_receipts = receipts.list_by_correlation_id("correlation-keep-me")
    finally:
        database.close()

    assert len(worklist.items) == 1
    assert decision.reservation_pending is True
    assert decision.existing_receipt_id is None
    assert decision.operator_resolved is False
    assert decision.not_submitted_resolution is None
    assert persisted_receipt is None
    assert correlated_receipts == ()


def test_corrupt_evidence_is_unavailable_not_an_empty_worklist(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        observation_id = uuid4()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(uuid4()),
                    '{"observation_id": "not-a-uuid"}',
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error is not None
    assert 0 < len(worklist.error) <= 512
    assert str(observation_id) in worklist.error


def test_overlong_corrupt_row_identity_stays_unavailable_and_bounded(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        overlong_observation_id = "x" * 2000
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    overlong_observation_id,
                    str(uuid4()),
                    "not-json",
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error is not None
    assert worklist.error.startswith("quarantine evidence could not be decoded: ")
    assert 0 < len(worklist.error) <= 512
    assert "x" * 128 in worklist.error
    assert "x" * 129 not in worklist.error
    assert overlong_observation_id not in worklist.error


def test_store_read_failure_is_unavailable_and_requires_attention() -> None:
    worklist = QuarantineWorklistReadService(quarantine=_FailingQuarantinePort()).read()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.available is False
    assert worklist.items == ()
    assert worklist.error == "quarantine evidence read failed: OSError"
    assert worklist.requires_operator_reconciliation is True


def test_empty_worklist_is_ok_and_distinct_from_unavailable(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        empty = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(uuid4()),
                    str(uuid4()),
                    "not-json",
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        corrupt = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert empty.status is QuarantineWorklistStatus.OK
    assert empty.items == ()
    assert empty.error is None
    assert empty.requires_operator_reconciliation is False
    assert corrupt.status is QuarantineWorklistStatus.UNAVAILABLE
    assert corrupt.requires_operator_reconciliation is True
    assert corrupt != empty


def test_worklist_output_is_bounded_and_excludes_raw_payload_secrets(tmp_path) -> None:
    observation_id = uuid4()
    client_order_id = uuid4()
    payload = json.dumps(
        {
            "observation_id": str(observation_id),
            "kind": "BROKER_UNKNOWN",
            "client_order_id": str(client_order_id),
            "observed_at": "2026-01-02T00:00:00+00:00",
            "reason": "r" * 512,
            "request_correlation_id": "correlation-1",
            "source": "dhan",
            "broker_order_id": "BR-1",
            "outcome": "UNKNOWN",
            "order_status": "UNKNOWN",
            "access_token": "tok-secret-value",
            "raw_response": {"payload": "x" * 1000},
        }
    )
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(client_order_id),
                    payload,
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert worklist.status is QuarantineWorklistStatus.OK
    item = worklist.items[0]
    rendered = item.observation.to_payload()
    assert "tok-secret-value" not in rendered
    assert "raw_response" not in rendered
    assert "x" * 100 not in rendered
    assert len(item.observation.reason) <= 512
    assert len(item.observation.to_payload()) < 2048


def test_worklist_limit_is_validated_and_reported_as_truncated() -> None:
    observations = tuple(
        _observation(observed_at=datetime(2026, 1, day, tzinfo=UTC)) for day in (1, 2, 3)
    )
    port = _StrictReadOnlyQuarantinePort(observations)
    service = QuarantineWorklistReadService(quarantine=port)

    truncated = service.read(limit=2)
    complete = service.read(limit=3)

    assert len(truncated.items) == 2
    assert truncated.truncated is True
    assert complete.truncated is False
    assert len(complete.items) == 3

    for invalid in (0, -1, 1001, True):
        with pytest.raises(ValueError):
            service.read(limit=invalid)


def test_missing_database_is_not_reported_as_an_empty_worklist(tmp_path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        SqliteDatabase.open_existing(missing)
    assert missing.exists() is False

    existing = tmp_path / "quantx.db"
    with SqliteDatabase(existing):
        pass
    with SqliteDatabase.open_existing(existing) as database:
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()

    assert worklist.status is QuarantineWorklistStatus.OK
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None


def test_worklist_limit_boundaries_are_exact() -> None:
    observations = tuple(
        _observation(observed_at=datetime(2026, 1, 1, tzinfo=UTC)) for _ in range(1000)
    )
    port = _StrictReadOnlyQuarantinePort(observations)
    complete = QuarantineWorklistReadService(quarantine=port).read(limit=1000)

    assert len(complete.items) == 1000
    assert complete.truncated is False
    assert complete.next_cursor is None

    with_extra = _observation(observed_at=datetime(2026, 1, 1, tzinfo=UTC))
    port = _StrictReadOnlyQuarantinePort((*observations, with_extra))
    service = QuarantineWorklistReadService(quarantine=port)
    first = service.read(limit=1000)
    second = service.read(limit=1000, cursor=first.next_cursor)

    assert len(first.items) == 1000
    assert first.truncated is True
    assert first.next_cursor is not None
    assert len(second.items) == 1
    assert second.truncated is False
    assert second.next_cursor is None
    assert {item.observation.observation_id for item in first.items}.isdisjoint(
        item.observation.observation_id for item in second.items
    )


def test_cursor_pages_are_contiguous_deterministic_and_non_overlapping() -> None:
    observations = tuple(
        _observation(observed_at=datetime(2026, 1, day, tzinfo=UTC)) for day in (1, 2, 3, 4, 5)
    )
    service = QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort(observations))
    expected = [
        observation.observation_id
        for observation in sorted(
            observations,
            key=lambda observation: (
                observation.observed_at,
                str(observation.observation_id),
            ),
        )
    ]

    seen = []
    cursor = None
    for _ in range(10):
        page = service.read(limit=2, cursor=cursor)
        seen.extend(item.observation.observation_id for item in page.items)
        assert page.truncated is (page.next_cursor is not None)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("cursor pagination did not terminate")

    assert seen == expected
    assert len(set(seen)) == len(seen)


def test_invalid_cursors_are_rejected_before_store_access() -> None:
    port = _StrictReadOnlyQuarantinePort(())
    service = QuarantineWorklistReadService(quarantine=port)
    invalid_cursors = (
        "",
        "not-a-cursor",
        "x" * 513,
        base64.urlsafe_b64encode(
            b'{"version":2,"observed_at":"2026-01-01T00:00:00+00:00",'
            b'"observation_id":"00000000-0000-0000-0000-000000000001"}'
        ).decode("ascii"),
        base64.urlsafe_b64encode(
            b'{"version":1,"observed_at":"2026-01-01T00:00:00",'
            b'"observation_id":"00000000-0000-0000-0000-000000000001"}'
        ).decode("ascii"),
    )

    for cursor in invalid_cursors:
        with pytest.raises(ValueError, match="cursor"):
            service.read(cursor=cursor)

    assert port.list_calls == 0


def test_worklist_result_rejects_contradictory_states() -> None:
    item = (
        QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort((_observation(),)))
        .read()
        .items[0]
    )

    with pytest.raises(ValueError):
        QuarantineWorklist(status=QuarantineWorklistStatus.OK, truncated=True)
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            items=(item,),
            truncated=True,
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            items=(item,),
            next_cursor="cursor",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            next_cursor="cursor",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            error="failed",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.UNAVAILABLE,
            items=(item,),
            error="failed",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.UNAVAILABLE,
            truncated=True,
            error="failed",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.UNAVAILABLE,
            next_cursor="cursor",
            error="failed",
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(status=QuarantineWorklistStatus.UNAVAILABLE)
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            items=[item],
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            truncated=1,
        )
    with pytest.raises(ValueError):
        QuarantineWorklist(status="OK")


def test_malformed_repository_results_fail_closed() -> None:
    observation = _observation()
    for malformed in (
        [observation],
        ("not-an-observation",),
        (observation, observation),
        None,
    ):
        worklist = QuarantineWorklistReadService(
            quarantine=_ScriptedQuarantinePort(malformed)
        ).read()
        assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
        assert worklist.items == ()
        assert worklist.truncated is False
        assert worklist.next_cursor is None
        assert worklist.error is not None
        assert 0 < len(worklist.error) <= 512


def test_read_bound_failure_is_unavailable_and_requires_attention() -> None:
    worklist = QuarantineWorklistReadService(
        quarantine=_RaisingQuarantinePort(
            QuarantineEvidenceTooLarge("row count exceeds the bounded scan")
        )
    ).read()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None
    assert worklist.requires_operator_reconciliation is True
    assert worklist.error is not None
    assert worklist.error.startswith("quarantine evidence exceeds read bounds: ")
    assert 0 < len(worklist.error) <= 512


def test_recursion_error_is_unavailable_but_process_control_exceptions_propagate() -> None:
    recursive = QuarantineWorklistReadService(
        quarantine=_RaisingQuarantinePort(RecursionError("nested evidence"))
    ).read()
    assert recursive.status is QuarantineWorklistStatus.UNAVAILABLE
    assert recursive.error == "quarantine evidence read failed: RecursionError"

    for error in (KeyboardInterrupt(), SystemExit()):
        service = QuarantineWorklistReadService(quarantine=_RaisingQuarantinePort(error))
        with pytest.raises(type(error)):
            service.read()


def test_over_bound_payload_is_unavailable_not_a_partial_worklist(tmp_path) -> None:
    observation_id = uuid4()
    client_order_id = uuid4()
    payload = json.dumps(
        {
            "observation_id": str(observation_id),
            "kind": "BROKER_UNKNOWN",
            "client_order_id": str(client_order_id),
            "observed_at": "2026-01-02T00:00:00+00:00",
            "reason": "bounded reason",
            "request_correlation_id": None,
            "source": "dhan",
            "broker_order_id": "BR-1",
            "outcome": "UNKNOWN",
            "order_status": "UNKNOWN",
            "padding": "x" * 5000,
        }
    )
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    str(observation_id),
                    str(client_order_id),
                    payload,
                    datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
        stored = (
            database.connection()
            .execute("SELECT COUNT(*) FROM submission_quarantine")
            .fetchone()[0]
        )

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None
    assert worklist.error is not None
    assert "payload exceeds" in worklist.error
    assert str(observation_id) in worklist.error
    assert stored == 1


def test_scan_bound_is_unavailable_and_leaves_evidence_untouched(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database, max_scan_rows=2)
        for _ in range(3):
            repository.record(_observation())
        before = _durable_snapshot(database)
        worklist = QuarantineWorklistReadService(quarantine=repository).read()
        after = _durable_snapshot(database)

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error is not None
    assert "row count exceeds" in worklist.error
    assert after == before


def test_renderer_neutralizes_control_text_without_changing_evidence(tmp_path) -> None:
    reason = "first line\nsecond line\r\x1b[31mred\x00\x9b"
    source = "dhan\rspoofed-entry"
    observation = _observation(reason=reason, source=source)
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        before = _durable_snapshot(database)
        worklist = QuarantineWorklistReadService(quarantine=repository).read()
        stored = repository.get(observation.observation_id)
        rendered = render_quarantine_worklist_item(worklist.items[0])
        after = _durable_snapshot(database)

    assert worklist.status is QuarantineWorklistStatus.OK
    assert len(worklist.items) == 1
    assert stored is not None
    assert stored.reason == reason
    assert stored.source == source
    assert after == before
    assert "\x00" not in rendered
    assert "\x1b" not in rendered
    assert "\r" not in rendered
    assert "\\x1b[31mred" in rendered
    assert "\\x00" in rendered
    assert "\\x9b" in rendered
    assert "dhan\\rspoofed-entry" in rendered
    assert rendered.count("\n") == 10


def test_rendered_item_is_bounded_even_with_maximal_control_text() -> None:
    control = "\x1b" * 256
    observation = _observation(
        reason="\x00" * 512,
        client_order_id=control,
        request_correlation_id=control,
        source=control,
        broker_order_id=control,
        outcome=control,
        order_status=control,
    )
    item = (
        QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort((observation,)))
        .read()
        .items[0]
    )

    rendered = render_quarantine_worklist_item(item)

    assert len(rendered) <= 4096
    assert rendered.endswith("...")
    assert "\x1b" not in rendered
    assert "\x00" not in rendered


def test_worklist_module_has_no_broker_or_network_imports() -> None:
    module_path = Path("src/quantx/application/quarantine_worklist.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module or "")

    forbidden = ("broker", "transport", "dhan", "socket", "requests", "urllib", "http")
    offenders = sorted(
        module for module in imported if any(token in module.lower() for token in forbidden)
    )
    assert offenders == []
