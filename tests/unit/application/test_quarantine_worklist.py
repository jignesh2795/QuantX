"""Read-only worklist tests for durable quarantined submission evidence."""

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from quantx.application.quarantine_worklist import (
    QuarantineEvidenceState,
    QuarantineWorklistReadService,
    QuarantineWorklistStatus,
)
from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
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
) -> QuarantinedSubmissionObservation:
    return QuarantinedSubmissionObservation(
        observation_id=observation_id or uuid4(),
        kind=kind,
        client_order_id=client_order_id or uuid4(),
        observed_at=observed_at or datetime(2026, 1, 2, tzinfo=UTC),
        reason="broker returned an UNKNOWN receipt; unresolved pending reconciliation",
        request_correlation_id="correlation-keep-me",
        source=source,
        broker_order_id=broker_order_id,
        outcome="UNKNOWN",
        order_status="UNKNOWN",
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

    reopened = SqliteDatabase(path)
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


def test_worklist_orders_items_deterministically_across_kinds_and_sources() -> None:
    late = _observation(
        kind=QuarantineObservationKind.MALFORMED_RECEIPT,
        observed_at=datetime(2026, 1, 3, tzinfo=UTC),
        source="dhan",
    )
    early_a = _observation(
        kind=QuarantineObservationKind.BROKER_UNKNOWN,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="fake-broker",
    )
    early_b = _observation(
        kind=QuarantineObservationKind.IDENTITY_REJECTED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="dhan",
    )
    port = _StrictReadOnlyQuarantinePort((late, early_a, early_b))

    first = QuarantineWorklistReadService(quarantine=port).read()
    second = QuarantineWorklistReadService(quarantine=port).read()

    expected = sorted(
        (late, early_a, early_b),
        key=lambda observation: (observation.observed_at, str(observation.observation_id)),
    )
    assert [item.observation.observation_id for item in first.items] == [
        observation.observation_id for observation in expected
    ]
    assert first == second
    assert port.list_calls == 2


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
    assert corrupt.status is QuarantineWorklistStatus.UNAVAILABLE
    assert corrupt != empty


def test_worklist_output_is_bounded_and_excludes_raw_payload_secrets(tmp_path) -> None:
    observation_id = uuid4()
    payload = json.dumps(
        {
            "observation_id": str(observation_id),
            "kind": "BROKER_UNKNOWN",
            "client_order_id": str(uuid4()),
            "observed_at": "2026-01-02T00:00:00+00:00",
            "reason": "r" * 512,
            "request_correlation_id": "correlation-1",
            "source": "dhan",
            "broker_order_id": "BR-1",
            "outcome": "UNKNOWN",
            "order_status": "UNKNOWN",
            "access_token": "tok-secret-value",
            "raw_response": {"payload": "x" * 5000},
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
                    str(uuid4()),
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
