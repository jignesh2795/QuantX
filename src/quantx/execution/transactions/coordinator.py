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
from quantx.persistence import ReceiptRepository


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
        receipt_repository: ReceiptRepository | None = None,
    ) -> None:
        self._idempotency = idempotency
        self._preconditions = preconditions
        self._submit = submit
        self._receipt_repository = receipt_repository

    def execute(self, request: ApprovedExecutionRequest) -> TransactionResult:
        preflight = self._preconditions(request)
        if not preflight.can_execute:
            return TransactionResult(preflight.status, reasons=preflight.reasons)

        fingerprint = request_fingerprint(request)
        client_order_id: UUID = request.order.client_order_id
        decision = self._idempotency.reserve_or_get(client_order_id, fingerprint)
        if decision.existing_receipt_id is not None:
            if self._receipt_repository is not None:
                authoritative = self._receipt_repository.get(decision.existing_receipt_id)
                if authoritative is None:
                    return TransactionResult(
                        PreconditionsStatus.UNKNOWN,
                        reasons=(
                            "persisted receipt is missing for a completed reservation; "
                            "reconciliation is required",
                        ),
                    )
                return TransactionResult(
                    PreconditionsStatus.READY,
                    receipt=authoritative,
                    reasons=(f"idempotent duplicate; receipt={decision.existing_receipt_id}",),
                )
            return TransactionResult(
                PreconditionsStatus.READY,
                reasons=(f"idempotent duplicate; receipt={decision.existing_receipt_id}",),
            )
        if decision.reservation_pending and not decision.reservation_acquired:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                reasons=("submission outcome is unknown; reconciliation is required",),
            )
        if not decision.reservation_acquired:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                reasons=("idempotency reservation was not acquired; reconciliation is required",),
            )
        try:
            receipt = self._submit(request)
        except Exception as exc:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                reasons=(f"submission outcome is unknown; reconciliation is required: {exc}",),
            )
        try:
            self._idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
        except Exception as exc:
            return TransactionResult(
                PreconditionsStatus.UNKNOWN,
                receipt=receipt,
                reasons=(
                    f"submission completed but idempotency completion is uncertain; "
                    f"reconciliation is required: {exc}",
                ),
            )
        return TransactionResult(PreconditionsStatus.READY, receipt=receipt)
