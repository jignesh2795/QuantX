"""Execution transaction coordinator with fail-closed semantics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.idempotency import IdempotencyStore
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import ExecutionReceipt
from quantx.execution.preconditions import PreconditionsResult, PreconditionsStatus


@dataclass(frozen=True, slots=True)
class TransactionResult:
    status: PreconditionsStatus
    receipt: ExecutionReceipt | None = None
    reasons: tuple[str, ...] = ()


class ExecutionTransactionCoordinator:
    """Coordinates preconditions, idempotency, submission, and receipt state."""

    def __init__(
        self,
        *,
        idempotency: IdempotencyStore,
        preconditions: Callable[[ApprovedExecutionRequest], PreconditionsResult],
        submit: Callable[[ApprovedExecutionRequest], ExecutionReceipt],
    ) -> None:
        self._idempotency = idempotency
        self._preconditions = preconditions
        self._submit = submit

    def execute(self, request: ApprovedExecutionRequest) -> TransactionResult:
        preflight = self._preconditions(request)
        if not preflight.can_execute:
            return TransactionResult(preflight.status, reasons=preflight.reasons)

        fingerprint = request_fingerprint(request)
        client_order_id: UUID = request.order.client_order_id
        decision = self._idempotency.check(client_order_id, fingerprint)
        if decision.existing_receipt_id is not None:
            return TransactionResult(
                PreconditionsStatus.READY,
                reasons=(f"idempotent duplicate; receipt={decision.existing_receipt_id}",),
            )
        if decision.reservation_pending:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                reasons=("submission outcome is unknown; reconciliation is required",),
            )

        self._idempotency.reserve(client_order_id, fingerprint)
        try:
            receipt = self._submit(request)
        except Exception as exc:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                reasons=(
                    "submission outcome is unknown; reconciliation is required: "
                    f"{exc}",
                ),
            )
        self._idempotency.complete(client_order_id, receipt.receipt_id)
        return TransactionResult(PreconditionsStatus.READY, receipt=receipt)
