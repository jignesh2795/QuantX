"""Safe continuation of partially filled execution requests.

This boundary derives a child execution only from authoritative lifecycle
evidence and a fresh risk approval. It does not implement retry policy,
broker-specific continuation semantics, or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskResult

from .dispatch import ExecutionDispatcher, ExecutionDispatchResult
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore, request_fingerprint
from .lifecycle import ExecutionLifecycleService
from .market_data import MarketSnapshot
from .receipts.lifecycle import ExecutionLifecycle
from .receipts.models import ExecutionReceipt


class PendingContinuationRecoveryState(StrEnum):
    """Explicit state of a continuation dispatch claim during recovery."""

    NOT_PENDING = "NOT_PENDING"
    PENDING = "PENDING"
    RECOVERABLE = "RECOVERABLE"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class PendingContinuationRecoveryStatus:
    """Non-dispatching inspection result for one pending continuation claim."""

    state: PendingContinuationRecoveryState
    receipt_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ExecutionContinuationResult:
    """Authoritative parent lifecycle, child request, and dispatch evidence."""

    parent_lifecycle: ExecutionLifecycle
    request: ApprovedExecutionRequest
    dispatch: ExecutionDispatchResult
    dispatch_performed: bool = True


@dataclass(frozen=True, slots=True)
class ExecutionContinuationDispatchReconciliation:
    """Dispatch evidence paired with authoritative child lifecycle state."""

    parent_lifecycle: ExecutionLifecycle
    request: ApprovedExecutionRequest
    dispatch: ExecutionDispatchResult
    child_lifecycle: ExecutionLifecycle
    dispatch_performed: bool = True


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


@dataclass(frozen=True, slots=True)
class ExecutionContinuationChain:
    """Reconstructed lifecycle stages sharing one root execution lineage."""

    root_lifecycle: ExecutionLifecycle
    stages: tuple[ExecutionLifecycle, ...]

    @property
    def aggregate_filled_quantity(self) -> Decimal:
        return sum((stage.filled_quantity for stage in self.stages), Decimal("0"))

    @property
    def aggregate_remaining_quantity(self) -> Decimal:
        return self.root_lifecycle.order_quantity - self.aggregate_filled_quantity

    @property
    def latest_lifecycle(self) -> ExecutionLifecycle:
        """Return the lifecycle state at the end of the continuation chain."""
        return self.stages[-1]

    @property
    def can_continue(self) -> bool:
        """Whether the latest chain stage is still eligible for continuation."""
        return self.latest_lifecycle.can_continue

    @property
    def is_complete(self) -> bool:
        """Whether the latest stage is terminal or the aggregate is fully filled."""
        return self.latest_lifecycle.is_complete


class ExecutionContinuationService:
    """Continue a partial order using authoritative lifecycle evidence."""

    def __init__(
        self,
        lifecycle_service: ExecutionLifecycleService,
        dispatcher: ExecutionDispatcher,
        *,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service
        self._dispatcher = dispatcher
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()

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
        if not parent_lifecycle.can_continue:
            raise ValueError("continuation parent lifecycle cannot continue")
        if child_request.order.quantity > parent_lifecycle.remaining_quantity:
            raise ValueError("continuation request exceeds parent lifecycle remainder")
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

    def reconcile_chain(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
    ) -> ExecutionContinuationChain:
        """Rebuild every continuation stage under the root correlation."""
        stages: list[ExecutionLifecycle] = []
        parent_request = root_request
        parent_lifecycle = self._lifecycle_service.reconcile(root_request)
        if continuation_requests and not parent_lifecycle.can_continue:
            raise ValueError("continuation chain parent lifecycle cannot continue")
        for index, request in enumerate(continuation_requests):
            expected_parent_id = str(parent_request.order.client_order_id)
            if request.parent_client_order_id != expected_parent_id:
                raise ValueError("continuation chain parent linkage is invalid")
            if request.order.quantity > parent_lifecycle.remaining_quantity:
                raise ValueError("continuation request exceeds parent lifecycle remainder")
            stage = self._lifecycle_service.reconcile_correlated(
                request,
                expected_parent_id,
            )
            if stage.filled_quantity > parent_lifecycle.remaining_quantity:
                raise ValueError("continuation fills exceed parent lifecycle remainder")
            stages.append(stage)
            parent_request = request
            parent_lifecycle = stage
            if index < len(continuation_requests) - 1 and not parent_lifecycle.can_continue:
                raise ValueError("continuation chain stage lifecycle cannot continue")
        stage_tuple = tuple(stages)
        root = self._lifecycle_service.reconcile(root_request)
        total = root.filled_quantity + sum(
            (stage.filled_quantity for stage in stage_tuple),
            Decimal("0"),
        )
        if total > root.order_quantity:
            raise ValueError("continuation chain fills exceed root order quantity")
        return ExecutionContinuationChain(
            root_lifecycle=root,
            stages=(root, *stage_tuple),
        )

    def _prepare_chain_continuation(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None,
        required_margin: Decimal,
        requested_quantity: Decimal | None,
    ) -> tuple[ExecutionContinuationChain, ApprovedExecutionRequest]:
        chain = self.reconcile_chain(root_request, continuation_requests)
        latest_request = continuation_requests[-1] if continuation_requests else root_request
        if latest_request.order.client_order_id != chain.latest_lifecycle.client_order_id:
            raise ValueError("latest continuation request does not match chain lifecycle")
        if not chain.can_continue:
            raise ValueError("continuation chain latest lifecycle cannot continue")
        continuation = chain.latest_lifecycle.continuation_request(
            latest_request,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            requested_quantity=requested_quantity,
        )
        return chain, continuation

    def prepare_chain_continuation(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        required_margin: Decimal = Decimal("0"),
        requested_quantity: Decimal | None = None,
    ) -> ApprovedExecutionRequest:
        """Build the next child from the authoritative latest chain stage."""
        _, continuation = self._prepare_chain_continuation(
            root_request,
            continuation_requests,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            requested_quantity=requested_quantity,
        )
        return continuation

    def _validate_claimed_child_receipt(
        self,
        parent_request: ApprovedExecutionRequest,
        continuation: ApprovedExecutionRequest,
        receipt: ExecutionReceipt,
    ) -> None:
        """Validate receipt metadata before an idempotency claim can be reused."""
        child_id = continuation.order.client_order_id
        parent_id = str(parent_request.order.client_order_id)
        if receipt.client_order_id != child_id:
            raise ValueError("idempotency receipt does not match continuation request")
        if receipt.correlation_id != parent_id:
            raise ValueError("idempotency receipt has invalid continuation correlation")
        if receipt.order_id is not None and receipt.order_id != child_id:
            raise ValueError("idempotency receipt has invalid continuation order identity")
        if (
            receipt.order_quantity is not None
            and receipt.order_quantity != continuation.order.quantity
        ):
            raise ValueError("idempotency receipt has invalid continuation order quantity")
        if (
            receipt.account_id is not None
            and receipt.account_id != continuation.execution_context.account_id
        ):
            raise ValueError("idempotency receipt has invalid account binding")
        expected_connection = continuation.execution_context.broker_connection_id
        if receipt.connection_id is not None and receipt.connection_id != expected_connection:
            raise ValueError("idempotency receipt has invalid broker connection binding")

    def _authoritative_child_receipt(
        self,
        parent_request: ApprovedExecutionRequest,
        continuation: ApprovedExecutionRequest,
    ) -> ExecutionReceipt | None:
        repository = self._lifecycle_service.receipt_repository
        if repository is None:
            return None
        parent_id = str(parent_request.order.client_order_id)
        receipts = repository.list_by_correlation_id(parent_id)
        matches = tuple(
            receipt
            for receipt in receipts
            if receipt.client_order_id == continuation.order.client_order_id
        )
        if not matches:
            return None
        authoritative = max(
            matches,
            key=lambda receipt: (receipt.executed_at, str(receipt.receipt_id)),
        )
        self._validate_claimed_child_receipt(
            parent_request,
            continuation,
            authoritative,
        )
        return authoritative

    def _reuse_claimed_child(
        self,
        chain: ExecutionContinuationChain,
        parent_request: ApprovedExecutionRequest,
        continuation: ApprovedExecutionRequest,
        receipt_id: UUID,
    ) -> ExecutionContinuationResult:
        repository = self._lifecycle_service.receipt_repository
        if repository is None:
            raise ValueError("authoritative receipt repository is required for continuation reuse")
        receipt = repository.get(receipt_id)
        if receipt is None:
            raise ValueError(
                "idempotency store references a completed continuation receipt "
                "that is not available in the authoritative repository"
            )
        self._validate_claimed_child_receipt(parent_request, continuation, receipt)
        authoritative = self._authoritative_child_receipt(
            parent_request,
            continuation,
        )
        if authoritative is None:
            raise ValueError("idempotency claim has no authoritative continuation receipt")
        if authoritative.receipt_id != receipt.receipt_id:
            raise ValueError(
                "idempotency claim does not reference the authoritative continuation receipt"
            )
        return ExecutionContinuationResult(
            parent_lifecycle=chain.latest_lifecycle,
            request=continuation,
            dispatch=ExecutionDispatchResult(
                request=continuation,
                receipt=receipt,
            ),
            dispatch_performed=False,
        )

    def _dispatch_or_reuse_chain_continuation(
        self,
        chain: ExecutionContinuationChain,
        parent_request: ApprovedExecutionRequest,
        continuation: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | None,
    ) -> ExecutionContinuationResult:
        fingerprint = request_fingerprint(continuation)
        decision = self._idempotency.reserve_or_get(
            continuation.order.client_order_id,
            fingerprint,
        )
        if decision.existing_receipt_id is not None:
            return self._reuse_claimed_child(
                chain,
                parent_request,
                continuation,
                decision.existing_receipt_id,
            )

        if decision.reservation_pending and not decision.reservation_acquired:
            authoritative = self._authoritative_child_receipt(
                parent_request,
                continuation,
            )
            if authoritative is None:
                raise ValueError(
                    "continuation dispatch is already pending and requires reconciliation"
                )
            try:
                self._idempotency.resolve_pending(
                    continuation.order.client_order_id,
                    fingerprint,
                    authoritative.receipt_id,
                )
            except ValueError:
                refreshed = self._idempotency.check(
                    continuation.order.client_order_id,
                    fingerprint,
                )
                if refreshed.existing_receipt_id != authoritative.receipt_id:
                    raise
            return ExecutionContinuationResult(
                parent_lifecycle=chain.latest_lifecycle,
                request=continuation,
                dispatch=ExecutionDispatchResult(
                    request=continuation,
                    receipt=authoritative,
                ),
                dispatch_performed=False,
            )

        if not decision.reservation_acquired:
            raise ValueError("continuation dispatch claim could not be acquired")

        authoritative = self._authoritative_child_receipt(parent_request, continuation)
        if authoritative is not None:
            self._idempotency.complete(
                continuation.order.client_order_id,
                fingerprint,
                authoritative.receipt_id,
            )
            return ExecutionContinuationResult(
                parent_lifecycle=chain.latest_lifecycle,
                request=continuation,
                dispatch=ExecutionDispatchResult(
                    request=continuation,
                    receipt=authoritative,
                ),
                dispatch_performed=False,
            )

        dispatched = self._dispatcher.dispatch(continuation, snapshot=snapshot)
        self._validate_claimed_child_receipt(
            parent_request,
            continuation,
            dispatched.receipt,
        )
        self._idempotency.complete(
            continuation.order.client_order_id,
            fingerprint,
            dispatched.receipt.receipt_id,
        )
        return ExecutionContinuationResult(
            parent_lifecycle=chain.latest_lifecycle,
            request=continuation,
            dispatch=dispatched,
            dispatch_performed=True,
        )

    def inspect_pending_continuation(
        self,
        parent_request: ApprovedExecutionRequest,
        child_request: ApprovedExecutionRequest,
    ) -> PendingContinuationRecoveryStatus:
        """Inspect pending recovery state without dispatching or mutating a claim."""
        if child_request.parent_client_order_id != str(parent_request.order.client_order_id):
            raise ValueError("continuation child does not reference the parent order")
        fingerprint = request_fingerprint(child_request)
        decision = self._idempotency.check(
            child_request.order.client_order_id,
            fingerprint,
        )
        if decision.existing_receipt_id is not None:
            return PendingContinuationRecoveryStatus(
                state=PendingContinuationRecoveryState.RESOLVED,
                receipt_id=decision.existing_receipt_id,
            )
        if not decision.reservation_pending:
            return PendingContinuationRecoveryStatus(
                state=PendingContinuationRecoveryState.NOT_PENDING,
            )
        authoritative = self._authoritative_child_receipt(
            parent_request,
            child_request,
        )
        if authoritative is None:
            return PendingContinuationRecoveryStatus(
                state=PendingContinuationRecoveryState.PENDING,
            )
        self.reconcile_continuation(parent_request, child_request)
        return PendingContinuationRecoveryStatus(
            state=PendingContinuationRecoveryState.RECOVERABLE,
            receipt_id=authoritative.receipt_id,
        )

    def recover_pending_continuation(
        self,
        parent_request: ApprovedExecutionRequest,
        child_request: ApprovedExecutionRequest,
    ) -> ExecutionContinuationResult:
        """Resolve a pending continuation claim from authoritative receipt evidence."""
        if child_request.parent_client_order_id != str(parent_request.order.client_order_id):
            raise ValueError("continuation child does not reference the parent order")
        fingerprint = request_fingerprint(child_request)
        status = self.inspect_pending_continuation(
            parent_request,
            child_request,
        )
        if status.state is PendingContinuationRecoveryState.RESOLVED:
            raise ValueError("continuation dispatch is already completed")
        if status.state is PendingContinuationRecoveryState.NOT_PENDING:
            raise ValueError("continuation dispatch is not pending")
        if status.state is PendingContinuationRecoveryState.PENDING:
            raise ValueError(
                "authoritative continuation receipt evidence is unavailable for pending recovery"
            )
        repository = self._lifecycle_service.receipt_repository
        if repository is None or status.receipt_id is None:
            raise ValueError(
                "pending recovery receipt is unavailable in the authoritative repository"
            )
        authoritative = repository.get(status.receipt_id)
        if authoritative is None:
            raise ValueError(
                "pending recovery receipt is unavailable in the authoritative repository"
            )
        try:
            self._idempotency.resolve_pending(
                child_request.order.client_order_id,
                fingerprint,
                authoritative.receipt_id,
            )
        except ValueError:
            refreshed = self._idempotency.check(
                child_request.order.client_order_id,
                fingerprint,
            )
            if refreshed.existing_receipt_id != authoritative.receipt_id:
                raise
        parent_lifecycle = self._lifecycle_service.reconcile(parent_request)
        return ExecutionContinuationResult(
            parent_lifecycle=parent_lifecycle,
            request=child_request,
            dispatch=ExecutionDispatchResult(
                request=child_request,
                receipt=authoritative,
            ),
            dispatch_performed=False,
        )

    def inspect_pending_chain_continuation(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        child_request: ApprovedExecutionRequest,
    ) -> PendingContinuationRecoveryStatus:
        """Inspect recovery state after binding the claim to the latest chain stage."""
        self.reconcile_chain(root_request, continuation_requests)
        parent_request = continuation_requests[-1] if continuation_requests else root_request
        if child_request.parent_client_order_id != str(parent_request.order.client_order_id):
            raise ValueError("pending continuation child does not reference latest chain stage")
        return self.inspect_pending_continuation(parent_request, child_request)

    def recover_pending_chain_continuation(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        child_request: ApprovedExecutionRequest,
    ) -> ExecutionContinuationResult:
        """Recover the next chain child from authoritative evidence without dispatch."""
        self.reconcile_chain(root_request, continuation_requests)
        parent_request = continuation_requests[-1] if continuation_requests else root_request
        if child_request.parent_client_order_id != str(parent_request.order.client_order_id):
            raise ValueError("pending continuation child does not reference latest chain stage")
        return self.recover_pending_continuation(parent_request, child_request)

    def dispatch_chain_continuation(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        required_margin: Decimal = Decimal("0"),
        requested_quantity: Decimal | None = None,
        snapshot: MarketSnapshot | None = None,
    ) -> ExecutionContinuationResult:
        """Prepare and dispatch the next child from authoritative chain state."""
        chain, continuation = self._prepare_chain_continuation(
            root_request,
            continuation_requests,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            requested_quantity=requested_quantity,
        )
        return self._dispatch_or_reuse_chain_continuation(
            chain,
            continuation_requests[-1] if continuation_requests else root_request,
            continuation,
            snapshot=snapshot,
        )

    def dispatch_chain_continuation_and_reconcile(
        self,
        root_request: ApprovedExecutionRequest,
        continuation_requests: tuple[ApprovedExecutionRequest, ...],
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        required_margin: Decimal = Decimal("0"),
        requested_quantity: Decimal | None = None,
        snapshot: MarketSnapshot | None = None,
    ) -> ExecutionContinuationDispatchReconciliation:
        """Dispatch a continuation and require authoritative child reconciliation."""
        chain, continuation = self._prepare_chain_continuation(
            root_request,
            continuation_requests,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            requested_quantity=requested_quantity,
        )
        parent_request = continuation_requests[-1] if continuation_requests else root_request
        dispatched_result = self._dispatch_or_reuse_chain_continuation(
            chain,
            parent_request,
            continuation,
            snapshot=snapshot,
        )
        reconciliation = self.reconcile_continuation(
            parent_request,
            continuation,
        )
        return ExecutionContinuationDispatchReconciliation(
            parent_lifecycle=reconciliation.parent_lifecycle,
            request=continuation,
            dispatch=dispatched_result.dispatch,
            child_lifecycle=reconciliation.child_lifecycle,
            dispatch_performed=dispatched_result.dispatch_performed,
        )

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        requested_quantity: Decimal | None = None,
        snapshot: MarketSnapshot | None = None,
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
    "ExecutionContinuationChain",
    "PendingContinuationRecoveryState",
    "PendingContinuationRecoveryStatus",
    "ExecutionContinuationDispatchReconciliation",
    "ExecutionContinuationReconciliation",
    "ExecutionContinuationResult",
    "ExecutionContinuationService",
]
