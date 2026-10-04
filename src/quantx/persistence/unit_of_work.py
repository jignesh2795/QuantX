"""Database-neutral persistence contracts for atomic execution state.

The application layer owns transaction boundaries through UnitOfWork.
Repository implementations participate in that boundary so receipt
persistence and idempotency completion commit atomically. No SQLite
mechanics live here; the later adapter implements these protocols.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from quantx.execution.idempotency import (
    IdempotencyDecision,
    OperatorResolution,
    OperatorResolutionAction,
    PendingExecutionContext,
    PendingExecutionRecoveryRecord,
)
from quantx.execution.ports import ExecutionReceipt


class PersistentIdempotencyStore(Protocol):
    """Durable idempotency boundary preserving the frozen store semantics."""

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision: ...
    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
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
    ) -> OperatorResolution: ...
    def get_operator_resolution(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> OperatorResolution | None: ...

    def list_pending_recovery_records(
        self,
    ) -> tuple[PendingExecutionRecoveryRecord, ...]: ...

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]: ...


class ReceiptRepository(Protocol):
    """Authoritative persistent receipt boundary reusing the canonical receipt."""

    def save(self, receipt: ExecutionReceipt) -> None: ...
    def get(self, receipt_id: UUID) -> ExecutionReceipt | None: ...
    def get_by_client_order(self, client_order_id: UUID) -> ExecutionReceipt | None: ...
    def list_by_correlation_id(
        self, correlation_id: UUID | str
    ) -> tuple[ExecutionReceipt, ...]: ...


class UnitOfWork(Protocol):
    """Application-owned transaction boundary for execution persistence.

    Repositories are exposed only through the UnitOfWork so application
    code cannot split receipt persistence and idempotency completion
    across unrelated transactions. Exiting the context without error
    commits both; an error rolls both back.
    """

    @property
    def idempotency(self) -> PersistentIdempotencyStore: ...
    @property
    def receipts(self) -> ReceiptRepository: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> UnitOfWork: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
