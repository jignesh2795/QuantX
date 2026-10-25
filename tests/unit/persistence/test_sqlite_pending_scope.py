"""Durable SQLite pending-scope guard and fail-closed lookup tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from quantx.application.live_risk_evidence import PendingScopeStatus
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.persistence.sqlite import SqliteDatabase, SqlitePendingScopeGuard

CHECKED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _insert_pending(
    database: SqliteDatabase,
    *,
    client_order_id: str | None = None,
    fingerprint: str = "fingerprint-1",
    scope_status: str | None = "KNOWN",
    account_id: str | None = "acct-1",
    connection_id: str | None = "conn-1",
) -> str:
    client_id = client_order_id or str(uuid4())
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO idempotency_reservations "
            "(client_order_id, fingerprint, receipt_id, created_at, completed_at, "
            "pending_context_json) "
            "VALUES (?, ?, NULL, ?, NULL, '{}')",
            (client_id, fingerprint, CHECKED_AT.isoformat()),
        )
        if scope_status is not None:
            connection.execute(
                "INSERT INTO pending_execution_scopes "
                "(client_order_id, request_fingerprint, scope_status, account_id, "
                "connection_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    client_id,
                    fingerprint,
                    scope_status,
                    account_id if scope_status == "KNOWN" else None,
                    connection_id if scope_status == "KNOWN" else None,
                    CHECKED_AT.isoformat(),
                ),
            )
    return client_id


def _check(
    database: SqliteDatabase,
    *,
    account_id: str = "acct-1",
    connection_id: str = "conn-1",
):
    return SqlitePendingScopeGuard(database).check(
        AccountId(account_id),
        BrokerConnectionId(connection_id),
        checked_at=CHECKED_AT,
    )


def test_empty_store_is_clear() -> None:
    with SqliteDatabase(":memory:") as database:
        result = _check(database)
    assert result.status is PendingScopeStatus.CLEAR


def test_matching_unresolved_reservation_is_pending() -> None:
    with SqliteDatabase(":memory:") as database:
        _insert_pending(database)
        result = _check(database)
    assert result.status is PendingScopeStatus.PENDING


def test_pending_scope_matches_account_and_connection_pair() -> None:
    with SqliteDatabase(":memory:") as database:
        _insert_pending(database, account_id="acct-1", connection_id="conn-1")
        same_account_other_connection = _check(database, connection_id="conn-2")
        other_account_same_connection = _check(database, account_id="acct-2")
    assert same_account_other_connection.status is PendingScopeStatus.CLEAR
    assert other_account_same_connection.status is PendingScopeStatus.CLEAR


def test_unknown_scope_blocks_every_account_and_connection() -> None:
    with SqliteDatabase(":memory:") as database:
        _insert_pending(
            database,
            scope_status="UNKNOWN",
            account_id=None,
            connection_id=None,
        )
        result = _check(
            database,
            account_id="unrelated-account",
            connection_id="unrelated-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_missing_legacy_scope_blocks_every_account_and_connection() -> None:
    with SqliteDatabase(":memory:") as database:
        _insert_pending(database, scope_status=None)
        result = _check(
            database,
            account_id="unrelated-account",
            connection_id="unrelated-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_completed_reservation_does_not_block_scope() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database)
        with database.transaction() as connection:
            connection.execute(
                "UPDATE idempotency_reservations SET receipt_id = ? "
                "WHERE client_order_id = ?",
                ("receipt-1", client_id),
            )
        result = _check(database)
    assert result.status is PendingScopeStatus.CLEAR


def test_operator_resolved_reservation_does_not_block_scope() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database, fingerprint="fingerprint-operator")
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO operator_resolutions "
                "(client_order_id, fingerprint, operator_id, reason, resolved_at, "
                "action, evidence_reference, created_at) "
                "VALUES (?, ?, 'operator-1', 'manually closed unresolved outcome', ?, "
                "'CLOSE_UNRESOLVED', NULL, ?)",
                (
                    client_id,
                    "fingerprint-operator",
                    CHECKED_AT.isoformat(),
                    CHECKED_AT.isoformat(),
                ),
            )
        result = _check(database)
    assert result.status is PendingScopeStatus.CLEAR


def test_operator_resolution_with_mismatched_fingerprint_blocks_globally() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database, fingerprint="expected-fingerprint")
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO operator_resolutions "
                "(client_order_id, fingerprint, operator_id, reason, resolved_at, "
                "action, evidence_reference, created_at) "
                "VALUES (?, 'different-fingerprint', 'operator-1', "
                "'mismatched legacy resolution', ?, 'CLOSE_UNRESOLVED', NULL, ?)",
                (client_id, CHECKED_AT.isoformat(), CHECKED_AT.isoformat()),
            )
        result = _check(
            database,
            account_id="other-account",
            connection_id="other-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_not_submitted_resolution_with_mismatched_fingerprint_blocks_globally() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database, fingerprint="expected-fingerprint")
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO not_submitted_resolutions "
                "(client_order_id, fingerprint, source, reason, recorded_at, "
                "created_at) "
                "VALUES (?, 'different-fingerprint', 'ADAPTER_PREFLIGHT_REJECTION', "
                "'resolution mismatch', ?, ?)",
                (client_id, CHECKED_AT.isoformat(), CHECKED_AT.isoformat()),
            )
        result = _check(
            database,
            account_id="other-account",
            connection_id="other-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_blank_operator_identity_does_not_close_pending_reservation() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database, fingerprint="fingerprint-blank-operator")
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO operator_resolutions "
                "(client_order_id, fingerprint, operator_id, reason, resolved_at, "
                "action, evidence_reference, created_at) "
                "VALUES (?, 'fingerprint-blank-operator', '', 'operator closure', ?, "
                "'CLOSE_UNRESOLVED', NULL, ?)",
                (client_id, CHECKED_AT.isoformat(), CHECKED_AT.isoformat()),
            )
        result = _check(
            database,
            account_id="other-account",
            connection_id="other-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_conflicting_resolution_kinds_block_globally() -> None:
    with SqliteDatabase(":memory:") as database:
        client_id = _insert_pending(database, fingerprint="fingerprint-conflict")
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO operator_resolutions "
                "(client_order_id, fingerprint, operator_id, reason, resolved_at, "
                "action, evidence_reference, created_at) "
                "VALUES (?, 'fingerprint-conflict', 'operator-1', 'operator closure', ?, "
                "'CLOSE_UNRESOLVED', NULL, ?)",
                (client_id, CHECKED_AT.isoformat(), CHECKED_AT.isoformat()),
            )
            connection.execute(
                "INSERT INTO not_submitted_resolutions "
                "(client_order_id, fingerprint, source, reason, recorded_at, "
                "created_at) "
                "VALUES (?, 'fingerprint-conflict', 'ADAPTER_PREFLIGHT_REJECTION', "
                "'not submitted', ?, ?)",
                (client_id, CHECKED_AT.isoformat(), CHECKED_AT.isoformat()),
            )
        result = _check(
            database,
            account_id="other-account",
            connection_id="other-connection",
        )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_orphaned_quarantine_observation_blocks_globally() -> None:
    with SqliteDatabase(":memory:") as database:
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO submission_quarantine "
                "(observation_id, client_order_id, payload, created_at) "
                "VALUES (?, ?, '{}', ?)",
                (str(uuid4()), str(uuid4()), CHECKED_AT.isoformat()),
            )
        result = _check(database)
    assert result.status is PendingScopeStatus.UNKNOWN


def test_closed_database_returns_unknown() -> None:
    database = SqliteDatabase(":memory:")
    guard = SqlitePendingScopeGuard(database)
    database.close()
    result = guard.check(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        checked_at=CHECKED_AT,
    )
    assert result.status is PendingScopeStatus.UNKNOWN


def test_scope_index_is_present() -> None:
    with SqliteDatabase(":memory:") as database:
        indexes = {
            row[1]
            for row in database.connection().execute(
                "PRAGMA index_list('pending_execution_scopes')"
            )
        }
    assert "idx_pending_execution_scopes_by_scope" in indexes
