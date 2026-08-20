"""Small deterministic idempotency store for client-order submissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    client_order_id: UUID
    request_fingerprint: str
    existing_receipt_id: UUID | None = None


class IdempotencyStore(Protocol):
    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision: ...
    def reserve(self, client_order_id: UUID, request_fingerprint: str) -> None: ...
    def complete(self, client_order_id: UUID, receipt_id: UUID) -> None: ...


class InMemoryIdempotencyStore:
    """Process-local reference implementation; production storage is replaceable."""

    def __init__(self) -> None:
        self._fingerprints: dict[UUID, str] = {}
        self._receipts: dict[UUID, UUID] = {}

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        existing = self._fingerprints.get(client_order_id)
        if existing is not None and existing != request_fingerprint:
            raise ValueError("client_order_id was reused with a different request")
        return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            existing_receipt_id=self._receipts.get(client_order_id),
        )

    def reserve(self, client_order_id: UUID, request_fingerprint: str) -> None:
        self.check(client_order_id, request_fingerprint)
        self._fingerprints[client_order_id] = request_fingerprint

    def complete(self, client_order_id: UUID, receipt_id: UUID) -> None:
        if client_order_id not in self._fingerprints:
            raise ValueError("cannot complete an unreserved client_order_id")
        self._receipts[client_order_id] = receipt_id
