"""Small deterministic idempotency store for client-order submissions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    client_order_id: UUID
    request_fingerprint: str
    existing_receipt_id: UUID | None = None
    reservation_pending: bool = False


class IdempotencyStore(Protocol):
    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision: ...
    def reserve_or_get(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> IdempotencyDecision: ...
    def complete(
        self, client_order_id: UUID, request_fingerprint: str, receipt_id: UUID
    ) -> None: ...
    def resolve_pending(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None: ...


class InMemoryIdempotencyStore:
    """Process-local reference implementation; production storage is replaceable."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._fingerprints: dict[UUID, str] = {}
        self._receipts: dict[UUID, UUID] = {}

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is not None and existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            existing_receipt_id=self._receipts.get(client_order_id),
                reservation_pending=existing is not None and client_order_id not in self._receipts,
            )

    def reserve_or_get(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._lock:
            decision = self.check(client_order_id, request_fingerprint)
            if decision.existing_receipt_id is not None or decision.reservation_pending:
                return decision
            self._fingerprints[client_order_id] = request_fingerprint
            return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
                reservation_pending=True,
            )

    def complete(
        self, client_order_id: UUID, request_fingerprint: str, receipt_id: UUID
    ) -> None:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is None:
            raise ValueError("cannot complete an unreserved client_order_id")
            if existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if client_order_id in self._receipts:
                raise ValueError("cannot complete an already completed client_order_id")
            self._receipts[client_order_id] = receipt_id

    def resolve_pending(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None:
        decision = self.check(client_order_id, request_fingerprint)
        if not decision.reservation_pending:
            raise ValueError("cannot resolve a non-pending idempotency reservation")
        self._receipts[client_order_id] = receipt_id
