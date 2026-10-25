"""Durable, indexed LIVE pending-submission scope guard for SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from quantx.application.live_risk_evidence import PendingScopeResult, PendingScopeStatus
from quantx.domain.accounts import AccountId, BrokerConnectionId

from .database import SqliteDatabase


_UNKNOWN_REASON = "durable pending-scope evidence is missing, malformed, or unavailable"
_PENDING_REASON = "an unresolved submission exists for this account and broker connection"
_CLEAR_REASON = "no unresolved submission exists for this account and broker connection"


class SqlitePendingScopeGuard:
    """Read-only account/connection lookup; untrusted scope blocks globally."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def _unknown(
        self,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        checked_at: datetime,
    ) -> PendingScopeResult:
        return PendingScopeResult(
            account_id=account_id,
            connection_id=connection_id,
            status=PendingScopeStatus.UNKNOWN,
            reason=_UNKNOWN_REASON,
            checked_at=checked_at,
        )

    def check(
        self,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        *,
        checked_at: datetime,
    ) -> PendingScopeResult:
        """Return CLEAR only when every unresolved durable record has valid scope."""

        if type(account_id) is not AccountId:
            raise ValueError("pending scope account_id must be AccountId")
        if type(connection_id) is not BrokerConnectionId:
            raise ValueError("pending scope connection_id must be BrokerConnectionId")
        if (
            type(checked_at) is not datetime
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
        ):
            raise ValueError("pending scope checked_at must be a timezone-aware datetime")

        try:
            with self._database.read_transaction() as connection:
                orphaned_scope = connection.execute(
                    "SELECT 1 FROM pending_execution_scopes AS s "
                    "LEFT JOIN idempotency_reservations AS r "
                    "ON r.client_order_id = s.client_order_id "
                    "WHERE r.client_order_id IS NULL LIMIT 1"
                ).fetchone()
                if orphaned_scope is not None:
                    return self._unknown(account_id, connection_id, checked_at)

                orphaned_quarantine = connection.execute(
                    "SELECT 1 FROM submission_quarantine AS q "
                    "LEFT JOIN idempotency_reservations AS r "
                    "ON r.client_order_id = q.client_order_id "
                    "WHERE r.client_order_id IS NULL LIMIT 1"
                ).fetchone()
                if orphaned_quarantine is not None:
                    return self._unknown(account_id, connection_id, checked_at)

                unknown_pending = connection.execute(
                    "SELECT 1 "
                    "FROM idempotency_reservations AS r "
                    "LEFT JOIN pending_execution_scopes AS s "
                    "ON s.client_order_id = r.client_order_id "
                    "WHERE r.receipt_id IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM operator_resolutions AS o "
                    "WHERE o.client_order_id = r.client_order_id) "
                    "AND NOT EXISTS (SELECT 1 FROM not_submitted_resolutions AS n "
                    "WHERE n.client_order_id = r.client_order_id) "
                    "AND ("
                    "s.client_order_id IS NULL "
                    "OR s.scope_status <> 'KNOWN' "
                    "OR s.request_fingerprint <> r.fingerprint "
                    "OR typeof(s.account_id) <> 'text' "
                    "OR length(trim(s.account_id)) = 0 "
                    "OR typeof(s.connection_id) <> 'text' "
                    "OR length(trim(s.connection_id)) = 0"
                    ") LIMIT 1"
                ).fetchone()
                if unknown_pending is not None:
                    return self._unknown(account_id, connection_id, checked_at)

                matching_pending = connection.execute(
                    "SELECT 1 "
                    "FROM pending_execution_scopes AS s "
                    "JOIN idempotency_reservations AS r "
                    "ON r.client_order_id = s.client_order_id "
                    "WHERE s.scope_status = 'KNOWN' "
                    "AND s.account_id = ? "
                    "AND s.connection_id = ? "
                    "AND s.request_fingerprint = r.fingerprint "
                    "AND r.receipt_id IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM operator_resolutions AS o "
                    "WHERE o.client_order_id = r.client_order_id) "
                    "AND NOT EXISTS (SELECT 1 FROM not_submitted_resolutions AS n "
                    "WHERE n.client_order_id = r.client_order_id) "
                    "LIMIT 1",
                    (account_id.value, connection_id.value),
                ).fetchone()
        except (sqlite3.Error, RuntimeError):
            return self._unknown(account_id, connection_id, checked_at)

        if matching_pending is not None:
            return PendingScopeResult(
                account_id=account_id,
                connection_id=connection_id,
                status=PendingScopeStatus.PENDING,
                reason=_PENDING_REASON,
                checked_at=checked_at,
            )
        return PendingScopeResult(
            account_id=account_id,
            connection_id=connection_id,
            status=PendingScopeStatus.CLEAR,
            reason=_CLEAR_REASON,
            checked_at=checked_at,
        )


__all__ = ["SqlitePendingScopeGuard"]
