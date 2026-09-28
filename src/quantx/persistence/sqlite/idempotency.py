"""SQLite-backed durable idempotency store preserving frozen semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from quantx.execution.idempotency import IdempotencyDecision

from .database import SqliteDatabase


class SqliteIdempotencyStore:
    """Durable idempotency store with the frozen in-memory semantics."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id FROM idempotency_reservations "
                "WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
        if row is None:
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
            )
        fingerprint, receipt_id = row
        if fingerprint != request_fingerprint:
            raise ValueError("client_order_id was reused with a different request")
        return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            existing_receipt_id=UUID(receipt_id) if receipt_id is not None else None,
            reservation_pending=receipt_id is None,
        )

    def reserve_or_get(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> IdempotencyDecision:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT fingerprint, receipt_id FROM idempotency_reservations "
                "WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO idempotency_reservations "
                    "(client_order_id, fingerprint, receipt_id, created_at, completed_at) "
                    "VALUES (?, ?, NULL, ?, NULL)",
                    (str(client_order_id), request_fingerprint, datetime.now(UTC).isoformat()),
                )
                return IdempotencyDecision(
                    client_order_id=client_order_id,
                    request_fingerprint=request_fingerprint,
                    reservation_pending=True,
                    reservation_acquired=True,
                )
            fingerprint, receipt_id = row
            if fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if receipt_id is not None:
                return IdempotencyDecision(
                    client_order_id=client_order_id,
                    request_fingerprint=request_fingerprint,
                    existing_receipt_id=UUID(receipt_id),
                )
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                reservation_pending=True,
            )

    def complete(self, client_order_id: UUID, request_fingerprint: str, receipt_id: UUID) -> None:
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
