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
from quantx.execution.receipts.models import ExecutionOutcome
from quantx.execution.receipts.quarantine import (
    MAX_SERIALIZED_PAYLOAD_CHARS,
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


class _ReceiptStub:
    """Minimal broker receipt carrying only the sanitized observation inputs."""

    def __init__(
        self,
        *,
        source: object,
        broker_order_id: object,
        outcome: object,
        order_status: object,
    ) -> None:
        self.source = source
        self.broker_order_id = broker_order_id
        self.outcome = outcome
        self.order_status = order_status


def _hostile_text(length: int) -> str:
    """Fill exactly ``length`` code points with printable and control text."""
    markers = "dhan\x1b\n\u00e9\u20b9\x00"
    text = (markers * (length // len(markers) + 1))[:length]
    if text[-1].isspace():
        text = f"{text[:-1]}x"
    assert len(text) == length
    assert text.strip() == text
    return text


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


class _UppercaseUUID(UUID):
    """A valid UUID whose text rendering is not the canonical one."""

    def __str__(self) -> str:
        return super().__str__().upper()


class _BracedUUID(UUID):
    """A valid UUID whose text rendering uses the braced form."""

    def __str__(self) -> str:
        return "{" + super().__str__() + "}"


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


def test_duplicate_logical_observation_identity_with_distinct_timestamps_is_unavailable() -> None:
    observation_id = UUID("00000000-0000-0000-0000-000000000009")
    first = _observation(
        observation_id=observation_id,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = _observation(
        observation_id=observation_id,
        observed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    worklist = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort((first, second))
    ).read()

    # The ordering key includes the timestamp, so these rows would otherwise
    # paginate as two distinct observations. One logical identity is one piece
    # of evidence: the worklist must fail closed instead of double-counting it.
    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None
    assert worklist.requires_operator_reconciliation is True
    assert worklist.error is not None
    assert "duplicate logical observation identities" in worklist.error
    assert 0 < len(worklist.error) <= 512


def test_legacy_uuid_renderings_of_one_identity_are_unavailable(tmp_path) -> None:
    base = uuid4()
    first = _observation(
        observation_id=base,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = _observation(
        observation_id=base,
        observed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        with database.transaction() as connection:
            connection.executemany(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    (
                        str(base),
                        str(first.client_order_id),
                        first.to_payload(),
                        first.observed_at.isoformat(),
                    ),
                    (
                        # A legacy row keeps the caller's non-canonical text in
                        # its identity column; its payload decodes to the same
                        # logical UUID as the canonical row.
                        str(base).upper(),
                        str(second.client_order_id),
                        second.to_payload(),
                        second.observed_at.isoformat(),
                    ),
                ),
            )
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error is not None
    assert "duplicate logical observation identities" in worklist.error


def test_uuid_subclass_rendering_cannot_bypass_the_duplicate_identity_check() -> None:
    identity = UUID("00000000-0000-0000-0000-0000000000ab")
    first = _observation(
        observation_id=_UppercaseUUID(str(identity)),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = _observation(
        observation_id=_BracedUUID(str(identity)),
        observed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    worklist = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort((first, second))
    ).read()

    # Both values hold one UUID; only their text renderings differ. A
    # rendering-based identity check would pass them as two observations.
    assert str(first.observation_id) != str(second.observation_id)
    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None
    assert worklist.error is not None
    assert "duplicate logical observation identities" in worklist.error


def test_cursor_traversal_uses_the_canonical_uuid_identity_across_renderings() -> None:
    identities = (
        UUID("00000000-0000-0000-0000-0000000000aa"),
        UUID("00000000-0000-0000-0000-0000000000b0"),
        UUID("00000000-0000-0000-0000-00000000000f"),
        UUID("00000000-0000-0000-0000-000000000010"),
        UUID("00000000-0000-0000-0000-0000000000cc"),
    )
    renderings = (_UppercaseUUID, _BracedUUID, UUID, _BracedUUID, _UppercaseUUID)
    observations = tuple(
        _observation(
            observation_id=renderer(str(identity)),
            observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        for identity, renderer in zip(identities, renderings, strict=True)
    )
    service = QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort(observations))

    first = service.read(limit=2)
    assert first.truncated is True
    assert first.next_cursor is not None
    anchor_cursor = first.next_cursor

    seen = [item.observation.observation_id for item in first.items]
    cursor = anchor_cursor
    for _ in range(10):
        page = service.read(limit=2, cursor=cursor)
        seen.extend(item.observation.observation_id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("cursor pagination did not terminate")

    # Ordering is by identity value, so the mixed renderings cannot reorder
    # items or break cursor attribution between pages.
    assert seen == sorted(identities)
    assert len({str(UUID(int=value.int)) for value in seen}) == len(seen)

    # The anchor is the canonical identity, not the subclass rendering, so the
    # next page can still attribute it to the evidence it came from.
    cursor_payload = json.loads(base64.urlsafe_b64decode(anchor_cursor))
    assert cursor_payload["observation_id"] == str(
        UUID(int=first.items[-1].observation.observation_id.int)
    )


def test_worklist_reports_wrong_typed_persisted_metadata_as_corruption(tmp_path) -> None:
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

    # A payload the writer could never have produced is corruption, not
    # evidence to normalize: silently turning it into a readable observation
    # would hide a modified evidence store from the operator.
    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error is not None
    assert worklist.error.startswith("quarantine evidence could not be decoded: ")
    assert str(observation_id) in worklist.error


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


def test_driver_failure_is_unavailable_without_raw_driver_text(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        database.connection().close()
        worklist = QuarantineWorklistReadService(
            quarantine=SqliteSubmissionQuarantineRepository(database)
        ).read()
    finally:
        database.close()

    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.error == (
        "quarantine evidence store could not be read: "
        "the SQLite evidence connection is not usable for reading"
    )
    assert "closed database" not in (worklist.error or "")


def test_open_existing_exposes_the_selected_store_path_for_verification(tmp_path) -> None:
    path = tmp_path / "evidence-copy.db"
    other = tmp_path / "other.db"
    with SqliteDatabase(path):
        pass
    with SqliteDatabase(other):
        pass

    with SqliteDatabase.open_existing(path) as database:
        assert database.path == str(path.absolute())
        with SqliteDatabase.open_existing(other) as other_database:
            assert other_database.path != database.path

    with SqliteDatabase(":memory:") as in_memory:
        assert in_memory.path == ":memory:"


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


def test_cursor_reuse_against_another_store_is_rejected() -> None:
    first_store = tuple(
        _observation(observed_at=datetime(2026, 1, day, tzinfo=UTC)) for day in (1, 2, 3)
    )
    other_store = tuple(
        _observation(observed_at=datetime(2026, 2, day, tzinfo=UTC)) for day in (1, 2)
    )
    first = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort(first_store)
    ).read(limit=1)
    assert first.truncated is True
    assert first.next_cursor is not None

    with pytest.raises(ValueError, match="does not match the readable evidence"):
        QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort(other_store)).read(
            cursor=first.next_cursor
        )


def test_cursor_whose_anchor_was_removed_is_rejected() -> None:
    observations = tuple(
        _observation(observed_at=datetime(2026, 1, day, tzinfo=UTC)) for day in (1, 2, 3, 4)
    )
    service = QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort(observations))
    cursor = service.read(limit=2).next_cursor
    assert cursor is not None

    remaining_later_rows = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort(observations[2:])
    )
    with pytest.raises(ValueError, match="does not match the readable evidence"):
        remaining_later_rows.read(cursor=cursor)


def test_cursor_page_after_later_rows_disappear_is_ok_and_empty() -> None:
    observations = tuple(
        _observation(observed_at=datetime(2026, 1, day, tzinfo=UTC)) for day in (1, 2, 3, 4)
    )
    first = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort(observations)
    ).read(limit=2)
    cursor = first.next_cursor
    assert cursor is not None

    # The anchor (last item of the previous page) is still readable, but the
    # rows that followed it are gone. That is a real empty tail, not a lost
    # page: it is reported as OK with no items so an operator can distinguish
    # "nothing further" from "evidence unreadable".
    tail = QuarantineWorklistReadService(
        quarantine=_StrictReadOnlyQuarantinePort(tuple(item.observation for item in first.items))
    ).read(cursor=cursor)

    assert tail.status is QuarantineWorklistStatus.OK
    assert tail.items == ()
    assert tail.truncated is False
    assert tail.next_cursor is None
    assert tail.requires_operator_reconciliation is False


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


def test_default_worklist_reads_maximal_valid_payload(tmp_path) -> None:
    text = "\U0001f600" * 256
    observation = _observation(
        client_order_id=text,
        reason="\U0001f600" * 512,
        request_correlation_id=text,
        source=text,
        broker_order_id=text,
        outcome=text,
        order_status=text,
    )
    payload = observation.to_payload()
    assert 4096 < len(payload) <= MAX_SERIALIZED_PAYLOAD_CHARS

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        worklist = QuarantineWorklistReadService(quarantine=repository).read()

    assert worklist.status is QuarantineWorklistStatus.OK
    assert len(worklist.items) == 1
    assert worklist.items[0].observation.to_payload() == payload


def test_from_receipt_observation_with_bounded_hostile_text_is_readable(tmp_path) -> None:
    source = _hostile_text(256)
    broker_order_id = _hostile_text(256)
    request_correlation_id = _hostile_text(256)
    reason = _hostile_text(383) + "\u202e"
    observation = QuarantinedSubmissionObservation.from_receipt(
        observation_id=uuid4(),
        kind=QuarantineObservationKind.TRANSPORT_UNCERTAIN,
        client_order_id=uuid4(),
        request_correlation_id=request_correlation_id,
        receipt=_ReceiptStub(
            source=source,
            broker_order_id=broker_order_id,
            outcome=ExecutionOutcome.UNKNOWN,
            order_status=ExecutionOutcome.UNKNOWN,
        ),
        reason=reason,
        observed_at=datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC),
    )
    payload = observation.to_payload()
    assert len(source) == 256
    assert len(broker_order_id) == 256
    assert len(reason) == 384
    assert len(payload) <= MAX_SERIALIZED_PAYLOAD_CHARS

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        repository.record(observation)
        worklist = QuarantineWorklistReadService(quarantine=repository).read()
        stored = repository.get(observation.observation_id)

    assert worklist.status is QuarantineWorklistStatus.OK
    assert worklist.error is None
    assert len(worklist.items) == 1
    observation_out = worklist.items[0].observation
    assert observation_out == observation
    assert stored == observation
    assert observation_out.source == source
    assert observation_out.broker_order_id == broker_order_id
    assert observation_out.reason == reason

    rendered = render_quarantine_worklist_item(worklist.items[0])
    assert len(rendered) <= 4096
    assert "\x1b" not in rendered
    assert "\x00" not in rendered
    assert "\u202e" not in rendered
    assert "\\x1b" in rendered
    assert "\\u202e" in rendered
    assert rendered.count("\n") == 10


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
            "padding": "x" * (MAX_SERIALIZED_PAYLOAD_CHARS + 1),
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


def test_default_worklist_is_unavailable_above_ten_thousand_stored_rows(tmp_path) -> None:
    observations = tuple(_observation() for _ in range(10_001))
    rows = [
        (
            str(observation.observation_id),
            str(observation.client_order_id),
            observation.to_payload(),
            observation.observed_at.isoformat(),
        )
        for observation in observations
    ]
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteSubmissionQuarantineRepository(database)
        with database.transaction() as connection:
            connection.executemany(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) VALUES (?, ?, ?, ?)",
                rows,
            )
        before = (
            database.connection()
            .execute("SELECT COUNT(*) FROM submission_quarantine")
            .fetchone()[0]
        )
        worklist = QuarantineWorklistReadService(quarantine=repository).read(limit=1)
        after = (
            database.connection()
            .execute("SELECT COUNT(*) FROM submission_quarantine")
            .fetchone()[0]
        )

    # 10,001 readable rows exceed the documented bounded-scan ceiling: the
    # result is an explicit UNAVAILABLE, never a partial page presented as a
    # complete inventory, and the evidence is left untouched.
    assert worklist.status is QuarantineWorklistStatus.UNAVAILABLE
    assert worklist.items == ()
    assert worklist.truncated is False
    assert worklist.next_cursor is None
    assert worklist.error is not None
    assert "row count exceeds the 10000-row scan bound" in worklist.error
    assert before == 10_001
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


def test_renderer_neutralizes_bidi_controls() -> None:
    bidi = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    observation = _observation(
        reason=f"before{bidi}after",
        source=f"dhan{bidi}spoofed-entry",
    )
    item = (
        QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort((observation,)))
        .read()
        .items[0]
    )

    rendered = render_quarantine_worklist_item(item)

    for character in bidi:
        assert character not in rendered
    assert "\\u061c" in rendered
    assert "\\u202e" in rendered
    assert "dhan" in rendered
    assert "spoofed-entry" in rendered


def test_renderer_neutralizes_invisible_unicode_format_characters() -> None:
    invisible = "\u00ad\u200b\u2060\ufeff"
    observation = _observation(
        reason=f"before{invisible}after",
        source=f"dhan{invisible}spoofed-entry",
    )
    item = (
        QuarantineWorklistReadService(quarantine=_StrictReadOnlyQuarantinePort((observation,)))
        .read()
        .items[0]
    )

    rendered = render_quarantine_worklist_item(item)

    for character in invisible:
        assert character not in rendered
    assert "\\xad" in rendered
    for codepoint in (0x200B, 0x2060, 0xFEFF):
        assert f"\\u{codepoint:04x}" in rendered
    assert "before" in rendered
    assert "after" in rendered
    assert "dhan" in rendered
    assert "spoofed-entry" in rendered


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
    module_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "quantx"
        / "application"
        / "quarantine_worklist.py"
    )
    assert module_path.is_file()
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
