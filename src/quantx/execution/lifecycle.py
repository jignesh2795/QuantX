"""Execution lifecycle orchestration from dispatch and immutable receipts.

This module turns an approved execution request into an explicit lifecycle
state without owning broker-specific behavior, persistence implementation,
retry policy, or cancellation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.enums import OrderStatus

from quantx.persistence import ReceiptRepository

from .dispatch import ExecutionDispatchResult, ExecutionDispatcher
from .receipts.lifecycle import ExecutionLifecycle
from .receipts.models import ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ExecutionLifecycleResult:
    """Dispatch evidence together with the reconstructed order lifecycle."""

    dispatch: ExecutionDispatchResult
    lifecycle: ExecutionLifecycle


class ExecutionLifecycleService:
    """Coordinate dispatch evidence into an authoritative order lifecycle."""

    def __init__(
        self,
        dispatcher: ExecutionDispatcher,
        *,
        receipt_repository: ReceiptRepository | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._receipt_repository = receipt_repository

    @property
    def receipt_repository(self) -> ReceiptRepository | None:
        return self._receipt_repository

    def dispatch(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot=None,
    ) -> ExecutionLifecycleResult:
        """Dispatch once and derive lifecycle state from available receipts."""
        dispatched = self._dispatcher.dispatch(request, snapshot=snapshot)
        receipts = self._receipts_for_dispatch(request, dispatched.receipt)
        lifecycle = ExecutionLifecycle.rebuild(
            request.order.client_order_id,
            request.order.quantity,
            receipts,
        )
        return ExecutionLifecycleResult(dispatch=dispatched, lifecycle=lifecycle)

    def reconcile(
        self,
        request: ApprovedExecutionRequest,
    ) -> ExecutionLifecycle:
        """Rebuild lifecycle from authoritative persisted receipt evidence."""
        if self._receipt_repository is None:
            raise ValueError("authoritative receipt repository is required for reconciliation")
        receipts = self._receipt_repository.list_by_correlation_id(
            request.order.client_order_id
        )
        if not receipts:
            raise ValueError("authoritative execution receipts are unavailable")
        return ExecutionLifecycle.rebuild(
            request.order.client_order_id,
            request.order.quantity,
            receipts,
        )

    def _receipts_for_dispatch(
        self,
        request: ApprovedExecutionRequest,
        receipt: ExecutionReceipt,
    ) -> tuple[ExecutionReceipt, ...]:
        if self._receipt_repository is None:
            return (receipt,)

        persisted = self._receipt_repository.list_by_correlation_id(
            request.order.client_order_id
        )
        if not persisted:
            return (receipt,)
        return persisted


__all__ = ["ExecutionLifecycleResult", "ExecutionLifecycleService"]
