"""SQLite-backed durable idempotency store preserving frozen semantics."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from quantx.execution.idempotency import (
    IdempotencyDecision,
    OperatorResolution,
    OperatorResolutionAction,
    PendingExecutionContext,
    PendingExecutionRecoveryRecord,
)

from .database import SqliteDatabase


class SqliteIdempotencyStore:
    """Durable idempotency store with recoverable pending request context."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def _decode_context(
        self,
        client_order_id: str,
        request_fingerprint: str,
        context_json: str,
    ) -> PendingExecutionContext:
        try:
            context = PendingExecutionContext.from_json(context_json)
        except ValueError as exc:
            raise ValueError(f"invalid pending execution context: {exc}") from exc
        if context.request_fingerprint != request_fingerprint:
            raise ValueError("pending execution context fingerprint does not match reservation")
        if str(context.order.client_order_id) != client_order_id:
            raise ValueError("pending execution context client_order_id does not match reservation")
        return context

    def _resolution(
        self,
        connection: sqlite3.Connection,
        client_order_id: UUID,
        request_fingerprint: str,
    ) -> OperatorResolution | None:
        row = connection.execute(
            "SELECT fingerprint, operator_id, reason, resolved_at, action, "
            "evidence_reference FROM operator_resolutions WHERE client_order_id = ?",
            (str(client_order_id),),
        ).fetchone()
        if row is None:
            return None
        fingerprint, operator_id, reason, resolved_at, action, evidence_reference = row
        if fingerprint != request_fingerprint:
            raise ValueError("client_order_id was reused with a different request")
        return OperatorResolution(
            client_order_id=client_order_id,
            request_fingerprint=fingerprint,
            operator_id=operator_id,
            reason=reason,
            resolved_at=datetime.fromisoformat(resolved_at),
            action=OperatorResolutionAction(action),
            evidence_reference=evidence_reference,
        )

    def _decision(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        row: tuple[str, str | None, str | None] | None,
        resolution: OperatorResolution | None = None,
    ) -> IdempotencyDecision:
        if row is None:
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
            )
        fingerprint, receipt_id, context_json = row
        if fingerprint != request_fingerprint:
            raise ValueError("client_order_id was reused with a different request")
        if resolution is not None and resolution.request_fingerprint != request_fingerprint:
            raise ValueError("client_order_id was reused with a different request")
        context = (
            self._decode_context(
                str(client_order_id),
                request_fingerprint,
                context_json,
            )
            if context_json is not None
            else None
        )
        return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            existing_receipt_id=UUID(receipt_id) if receipt_id is not None else None,
            reservation_pending=receipt_id is None and resolution is None,
            pending_context=context,
            operator_resolved=resolution is not None,
            operator_resolution=resolution,
        )

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id, pending_context_json "
                "FROM idempotency_reservations WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            resolution = self._resolution(connection, client_order_id, request_fingerprint)
        return self._decision(client_order_id, request_fingerprint, row, resolution)

    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
    ) -> IdempotencyDecision:
        if pending_context is not None:
            if pending_context.request_fingerprint != request_fingerprint:
                raise ValueError("pending execution context fingerprint does not match reservation")
            if pending_context.order.client_order_id != client_order_id:
                raise ValueError(
                    "pending execution context client_order_id does not match reservation"
                )
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id, pending_context_json "
                "FROM idempotency_reservations WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO idempotency_reservations "
                    "(client_order_id, fingerprint, receipt_id, created_at, completed_at, "
                    "pending_context_json) VALUES (?, ?, NULL, ?, NULL, ?)",
                    (
                        str(client_order_id),
                        request_fingerprint,
                        datetime.now(UTC).isoformat(),
                        None if pending_context is None else pending_context.to_json(),
                    ),
                )
                return IdempotencyDecision(
                    client_order_id=client_order_id,
                    request_fingerprint=request_fingerprint,
                    reservation_pending=True,
                    reservation_acquired=True,
                    pending_context=pending_context,
                )
            resolution = self._resolution(connection, client_order_id, request_fingerprint)
        return self._decision(client_order_id, request_fingerprint, row, resolution)

    def complete(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id FROM idempotency_reservations "
                "WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                raise ValueError("cannot complete an unreserved client_order_id")
            fingerprint, existing = row
            if fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if self._resolution(connection, client_order_id, request_fingerprint) is not None:
                raise ValueError("cannot complete an operator-resolved reservation")
            if existing is not None:
                raise ValueError("cannot complete an already completed client_order_id")
            connection.execute(
                "UPDATE idempotency_reservations SET receipt_id = ?, completed_at = ? "
                "WHERE client_order_id = ?",
                (str(receipt_id), datetime.now(UTC).isoformat(), str(client_order_id)),
            )

    def resolve_pending(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id FROM idempotency_reservations "
                "WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                raise ValueError("cannot resolve a non-pending idempotency reservation")
            fingerprint, existing = row
            if fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if self._resolution(connection, client_order_id, request_fingerprint) is not None:
                raise ValueError("cannot resolve an operator-resolved reservation")
            if existing is not None:
                raise ValueError("cannot resolve a non-pending idempotency reservation")
            connection.execute(
                "UPDATE idempotency_reservations SET receipt_id = ?, completed_at = ? "
                "WHERE client_order_id = ?",
                (str(receipt_id), datetime.now(UTC).isoformat(), str(client_order_id)),
            )

    def resolve_operator(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        operator_id: str,
        reason: str,
        resolved_at: datetime,
        action: OperatorResolutionAction = OperatorResolutionAction.CLOSE_UNRESOLVED,
        evidence_reference: str | None = None,
    ) -> OperatorResolution:
        """Atomically close a PENDING reservation with an audited record.

        The reservation check and the audit insert share one transaction and
        perform no broker calls. Completed or already-resolved reservations
        fail closed without overwriting history, and no ExecutionReceipt is
        created.
        """
        resolution = OperatorResolution(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            operator_id=operator_id,
            reason=reason,
            resolved_at=resolved_at,
            action=action,
            evidence_reference=evidence_reference,
        )
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id FROM idempotency_reservations "
                "WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                raise ValueError("cannot resolve an unreserved client_order_id")
            fingerprint, existing = row
            if fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if existing is not None:
                raise ValueError("cannot operator-resolve a completed reservation")
            if self._resolution(connection, client_order_id, request_fingerprint) is not None:
                raise ValueError("reservation is already operator-resolved")
            connection.execute(
                "INSERT INTO operator_resolutions "
                "(client_order_id, fingerprint, operator_id, reason, resolved_at, "
                "action, evidence_reference, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(client_order_id),
                    request_fingerprint,
                    resolution.operator_id,
                    resolution.reason,
                    resolution.resolved_at.isoformat(),
                    resolution.action.value,
                    resolution.evidence_reference,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return resolution

    def get_operator_resolution(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> OperatorResolution | None:
        with self._database.transaction() as connection:
            return self._resolution(connection, client_order_id, request_fingerprint)

    def list_pending_recovery_records(self) -> tuple[PendingExecutionRecoveryRecord, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT client_order_id, fingerprint, pending_context_json "
                "FROM idempotency_reservations "
                "WHERE receipt_id IS NULL AND pending_context_json IS NOT NULL "
                "AND client_order_id NOT IN "
                "(SELECT client_order_id FROM operator_resolutions) "
                "ORDER BY created_at"
            ).fetchall()
        records = []
        for client_order_id, fingerprint, context_json in rows:
            try:
                context = self._decode_context(client_order_id, fingerprint, context_json)
            except ValueError as exc:
                records.append(
                    PendingExecutionRecoveryRecord(
                        client_order_id=client_order_id,
                        request_fingerprint=fingerprint,
                        error=str(exc),
                    )
                )
            else:
                records.append(
                    PendingExecutionRecoveryRecord(
                        client_order_id=client_order_id,
                        request_fingerprint=fingerprint,
                        context=context,
                    )
                )
        return tuple(records)

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]:
        return tuple(
            record.context
            for record in self.list_pending_recovery_records()
            if record.context is not None
        )
