"""Safe continuation of partially filled execution requests.

This boundary derives a child execution only from authoritative lifecycle
evidence and a fresh risk approval. It does not implement retry policy,
broker-specific continuation semantics, or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskResult

from .dispatch import ExecutionDispatchResult, ExecutionDispatcher
from .receipts.lifecycle import ExecutionLifecycle
from .lifecycle import ExecutionLifecycleService


@dataclass(frozen=True, slots=True)
class ExecutionContinuationResult:
    """Authoritative parent lifecycle, child request, and dispatch evidence."""

    parent_lifecycle: ExecutionLifecycle
    request: ApprovedExecutionRequest
    dispatch: ExecutionDispatchResult


@dataclass(frozen=True, slots=True)
class ExecutionContinuationReconciliation:
    """Reconstructed parent and child lifecycle state from receipt history."""

    parent_lifecycle: ExecutionLifecycle
    child_lifecycle: ExecutionLifecycle

    @property
    def aggregate_filled_quantity(self) -> Decimal:
        return self.parent_lifecycle.filled_quantity + self.child_lifecycle.filled_quantity

    @property
    def aggregate_remaining_quantity(self) -> Decimal:
        return self.parent_lifecycle.order_quantity - self.aggregate_filled_quantity


class ExecutionContinuationService:
    """Continue a partial order using authoritative lifecycle evidence."""

    def __init__(
        self,
        lifecycle_service: ExecutionLifecycleService,
        dispatcher: ExecutionDispatcher,
    ) -> None:
        self._lifecycle_service = lifecycle_service
        self._dispatcher = dispatcher

    def reconcile_continuation(
        self,
        parent_request: ApprovedExecutionRequest,
        child_request: ApprovedExecutionRequest,
    ) -> ExecutionContinuationReconciliation:
        """Rebuild a continuation child without losing its parent correlation."""
        parent_id = str(parent_request.order.client_order_id)
        if child_request.parent_client_order_id != parent_id:
            raise ValueError("continuation child does not reference the parent order")
        repository = self._lifecycle_service.receipt_repository
        if repository is None:
            raise ValueError("authoritative receipt repository is required for reconciliation")
        receipts = repository.list_by_correlation_id(parent_request.order.client_order_id)
        if not receipts:
            raise ValueError("authoritative execution receipts are unavailable")
        child_receipts = tuple(
            receipt
            for receipt in receipts
            if receipt.client_order_id == child_request.order.client_order_id
        )
        if not child_receipts:
            raise ValueError("authoritative continuation receipt evidence is unavailable")
        parent_lifecycle = self._lifecycle_service.reconcile(parent_request)
        child_lifecycle = ExecutionLifecycle.rebuild(
            child_request.order.client_order_id,
            child_request.order.quantity,
            child_receipts,
            correlation_id=parent_id,
        )
        if child_lifecycle.filled_quantity > parent_lifecycle.remaining_quantity:
            raise ValueError("continuation fills exceed parent lifecycle remainder")
        return ExecutionContinuationReconciliation(
            parent_lifecycle=parent_lifecycle,
            child_lifecycle=child_lifecycle,
        )

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        requested_quantity: Decimal | None = None,
        snapshot=None,
    ) -> ExecutionContinuationResult:
        """Build and dispatch one fresh child for the evidenced remainder."""
        lifecycle = self._lifecycle_service.reconcile(request)
        continuation = lifecycle.continuation_request(
            request,
            risk_result=risk_result,
            policy_result=policy_result,
            requested_quantity=requested_quantity,
        )
        dispatched = self._dispatcher.dispatch(continuation, snapshot=snapshot)
        return ExecutionContinuationResult(
            parent_lifecycle=lifecycle,
            request=continuation,
            dispatch=dispatched,
        )


__all__ = [
    "ExecutionContinuationReconciliation",
    "ExecutionContinuationResult",
    "ExecutionContinuationService",
]
