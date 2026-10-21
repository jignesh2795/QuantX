"""Database-neutral persistence contracts consumed by the execution core.

These protocols are the stable boundary that execution and application code
depend on; persistence adapters (``quantx.persistence.sqlite``) implement them.
The application layer owns transaction boundaries through :class:`UnitOfWork`.
Repository implementations participate in that boundary so receipt persistence
and idempotency completion commit atomically. No storage mechanics live here.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from quantx.execution.idempotency import (
    IdempotencyDecision,
    NotSubmittedResolution,
    NotSubmittedSource,
    OperatorResolution,
    OperatorResolutionAction,
    PendingExecutionContext,
    PendingExecutionRecoveryRecord,
)
from quantx.execution.ports import ExecutionReceipt
from quantx.execution.receipts.quarantine import QuarantinedSubmissionObservation


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
    def record_not_submitted(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        source: NotSubmittedSource,
        reason: str,
        recorded_at: datetime,
    ) -> NotSubmittedResolution: ...
    def get_not_submitted(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> NotSubmittedResolution | None: ...

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


class SubmissionQuarantineRepository(Protocol):
    """Non-authoritative durable evidence store for uncertain submissions.

    Quarantined observations are separate from authoritative receipts and
    from canonical accounting/lifecycle calculations. They never satisfy
    idempotency completion and are never returned as canonical receipts;
    they exist so uncertain or rejected submission evidence survives for
    reconciliation. Writes are idempotent on the stable observation
    identity: re-recording an identical observation is a no-op, and a
    conflicting payload for the same identity fails closed.
    """

    def record(self, observation: QuarantinedSubmissionObservation) -> None: ...
    def get(self, observation_id: UUID) -> QuarantinedSubmissionObservation | None: ...
    def list_by_client_order(
        self, client_order_id: UUID | str
    ) -> tuple[QuarantinedSubmissionObservation, ...]: ...
    def list_all(self) -> tuple[QuarantinedSubmissionObservation, ...]:
        """Return all readable durable observations in storage order.

        Implementations must not mutate evidence, and must raise
        ``QuarantineEvidenceDecodeError`` rather than skip an unreadable or
        identity-inconsistent row. They must also enforce their documented
        retrieval bounds and raise ``QuarantineEvidenceTooLarge`` instead of
        silently omitting evidence beyond those bounds. Presentation ordering
        and pagination belong to the read consumer.
        """
        ...


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


__all__ = [
    "PersistentIdempotencyStore",
    "ReceiptRepository",
    "SubmissionQuarantineRepository",
    "UnitOfWork",
]
