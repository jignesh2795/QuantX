"""Idempotency keys and duplicate-submission protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Mapping


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("idempotency key must not be empty")

    @classmethod
    def from_order_fingerprint(cls, canonical: str) -> "IdempotencyKey":
        return cls(sha256(canonical.encode("utf-8")).hexdigest())


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    key: IdempotencyKey
    account_id: str
    connection_id: str
    client_order_id: str
    created_at: datetime
    state: str


class IdempotencyRegistry:
    """Keep submission identity separate from broker acknowledgment state."""

    def __init__(self) -> None:
        self._records: dict[str, SubmissionRecord] = {}

    def reserve(self, record: SubmissionRecord) -> bool:
        existing = self._records.get(record.key.value)
        if existing is not None:
            return False
        self._records[record.key.value] = record
        return True

    def get(self, key: IdempotencyKey) -> SubmissionRecord | None:
        return self._records.get(key.value)

    def update_state(self, key: IdempotencyKey, state: str) -> SubmissionRecord:
        existing = self._records.get(key.value)
        if existing is None:
            raise KeyError(key.value)
        updated = SubmissionRecord(
            key=existing.key,
            account_id=existing.account_id,
            connection_id=existing.connection_id,
            client_order_id=existing.client_order_id,
            created_at=existing.created_at,
            state=state,
        )
        self._records[key.value] = updated
        return updated

    def all(self) -> tuple[SubmissionRecord, ...]:
        return tuple(self._records.values())
