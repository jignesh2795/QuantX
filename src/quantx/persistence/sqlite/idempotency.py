"""SQLite-backed durable idempotency store preserving frozen semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from quantx.execution.idempotency import (
    IdempotencyDecision,
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

    def _decision(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        row: tuple[str, str | None, str | None] | None,
    ) -> IdempotencyDecision:
        if row is None:
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
            )
        fingerprint, receipt_id, context_json = row
        if fingerprint != request_fingerprint:
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
            reservation_pending=receipt_id is None,
            pending_context=context,
        )

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id, pending_context_json "
                "FROM idempotency_reservations WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
        return self._decision(client_order_id, request_fingerprint, row)

    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
    ) -> IdempotencyDecision:
        if pending_context is not None:
            if pending_context.request_fingerprint != request_fingerprint:
                raise ValueError(
                    "pending execution context fingerprint does not match reservation"
                )
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
        return self._decision(client_order_id, request_fingerprint, row)

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
            if existing is not None:
                raise ValueError("cannot resolve a non-pending idempotency reservation")
            connection.execute(
                "UPDATE idempotency_reservations SET receipt_id = ?, completed_at = ? "
                "WHERE client_order_id = ?",
                (str(receipt_id), datetime.now(UTC).isoformat(), str(client_order_id)),
            )

    def list_pending_recovery_records(self) -> tuple[PendingExecutionRecoveryRecord, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT client_order_id, fingerprint, pending_context_json "
                "FROM idempotency_reservations "
                "WHERE receipt_id IS NULL AND pending_context_json IS NOT NULL "
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
