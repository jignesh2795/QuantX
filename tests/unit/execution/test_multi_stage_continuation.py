from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import Event, Lock
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import (
    ExecutionContinuationChain,
    ExecutionContinuationDispatchReconciliation,
)
from quantx.execution.idempotency import InMemoryIdempotencyStore, request_fingerprint
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.models import ExecutionOutcome

from .test_continuation import _PaperPort, _ReceiptRepository, _receipt, _request, _snapshot
from quantx.execution.continuation import ExecutionContinuationService
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.lifecycle import ExecutionLifecycleService


def _service(repository: _ReceiptRepository, receipt) -> ExecutionContinuationService:
    dispatcher = ExecutionDispatcher(paper_port=_PaperPort(receipt))
    lifecycle_service = ExecutionLifecycleService(
        dispatcher,
        receipt_repository=repository,
    )
    return ExecutionContinuationService(lifecycle_service, dispatcher)


def test_reconcile_two_sequential_continuations() -> None:
    root = _request()
    first_receipt = _receipt(root, "4")
    first_lifecycle = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (first_receipt,),
    )
    first = first_lifecycle.continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
        requested_quantity=Decimal("5"),
    )
    second_receipt = _receipt(first, "2")
    second_lifecycle = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (second_receipt,),
    )
    second = second_lifecycle.continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage two approval"),
    )
    third_receipt = _receipt(second, "3")

    repository = _ReceiptRepository(
        (first_receipt, second_receipt, third_receipt)
    )
    service = _service(repository, third_receipt)

    chain = service.reconcile_chain(root, (first, second))

    assert isinstance(chain, ExecutionContinuationChain)
    assert chain.root_lifecycle.filled_quantity == Decimal("4")
    assert chain.stages[1].filled_quantity == Decimal("2")
    assert chain.stages[2].filled_quantity == Decimal("3")
    assert chain.aggregate_filled_quantity == Decimal("9")
    assert chain.aggregate_remaining_quantity == Decimal("1")


def test_reconcile_chain_rejects_cumulative_overfill() -> None:
    root = _request()
    first_receipt = _receipt(root, "6")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (first_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(first, "5")
    repository = _ReceiptRepository((first_receipt, child_receipt))
    service = _service(repository, child_receipt)

    with pytest.raises(ValueError, match="cumulative fills exceed order quantity"):
        service.reconcile_chain(root, (first,))


def test_reconcile_chain_is_idempotent_for_duplicate_stage_receipts() -> None:
    root = _request()
    first_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (first_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(first, "6")
    repository = _ReceiptRepository((first_receipt, child_receipt, child_receipt))
    service = _service(repository, child_receipt)

    chain = service.reconcile_chain(root, (first,))

    assert chain.aggregate_filled_quantity == Decimal("10")
    assert chain.aggregate_remaining_quantity == Decimal("0")


def test_reconcile_chain_rejects_broken_parent_linkage() -> None:
    root = _request()
    first_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (first_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("5"),
    )
    second_receipt = _receipt(first, "2")
    second = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (second_receipt,),
    ).continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    malformed_second = second.__class__(
        order=second.order,
        execution_context=second.execution_context,
        risk_result=second.risk_result,
        policy_result=second.policy_result,
        required_margin=second.required_margin,
        parent_client_order_id=str(root.order.client_order_id),
    )
    repository = _ReceiptRepository((first_receipt, second_receipt))
    service = _service(repository, second_receipt)

    with pytest.raises(ValueError, match="parent linkage is invalid"):
        service.reconcile_chain(root, (first, malformed_second))



def test_reconcile_chain_rejects_stage_quantity_above_parent_remainder() -> None:
    root = _request()
    root_receipt = _receipt(root, "8")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    first_receipt = _receipt(first, "1")
    first_lifecycle = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (first_receipt,),
        correlation_id=str(root.order.client_order_id),
    )
    valid_second = first_lifecycle.continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    malformed_second = valid_second.__class__(
        order=valid_second.order.__class__(
            instrument=valid_second.order.instrument,
            side=valid_second.order.side,
            order_type=valid_second.order.order_type,
            quantity=Decimal("2"),
            limit_price=valid_second.order.limit_price,
            stop_price=valid_second.order.stop_price,
            time_in_force=valid_second.order.time_in_force,
            intent_id=valid_second.order.intent_id,
            client_order_id=valid_second.order.client_order_id,
            strategy_id=valid_second.order.strategy_id,
            strategy_version=valid_second.order.strategy_version,
            required_capabilities=valid_second.order.required_capabilities,
        ),
        execution_context=valid_second.execution_context,
        risk_result=valid_second.risk_result,
        policy_result=valid_second.policy_result,
        required_margin=valid_second.required_margin,
        parent_client_order_id=valid_second.parent_client_order_id,
    )
    repository = _ReceiptRepository((root_receipt, first_receipt))
    service = _service(repository, first_receipt)

    with pytest.raises(ValueError, match="exceeds parent lifecycle remainder"):
        service.reconcile_chain(root, (first, malformed_second))


def test_reconcile_chain_rejects_continuation_after_terminal_stage() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("5"),
    )
    first_receipt = _receipt(first, "1")
    second = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (first_receipt,),
        correlation_id=str(root.order.client_order_id),
    ).continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    terminal_receipt = _receipt(first, "4")
    repository = _ReceiptRepository((root_receipt, first_receipt, terminal_receipt))
    service = _service(repository, terminal_receipt)

    with pytest.raises(ValueError, match="stage lifecycle cannot continue"):
        service.reconcile_chain(root, (first, second))



def test_reconcile_chain_exposes_latest_partial_stage_as_continuable() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    first_receipt = _receipt(first, "2")
    repository = _ReceiptRepository((root_receipt, first_receipt))
    service = _service(repository, first_receipt)

    chain = service.reconcile_chain(root, (first,))

    assert chain.latest_lifecycle == chain.stages[-1]
    assert chain.latest_lifecycle.client_order_id == first.order.client_order_id
    assert chain.can_continue
    assert not chain.is_complete
    assert chain.aggregate_remaining_quantity == Decimal("4")


def test_reconcile_chain_exposes_terminal_latest_stage_as_complete() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("5"),
    )
    first_receipt = _receipt(first, "1")
    terminal_receipt = replace(
        first_receipt,
        outcome=ExecutionOutcome.CANCELLED,
        order_status=OrderStatus.CANCELLED,
        executed_at=first_receipt.executed_at + timedelta(minutes=1),
        fills=(),
        receipt_id=uuid4(),
    )
    repository = _ReceiptRepository((root_receipt, first_receipt, terminal_receipt))
    service = _service(repository, terminal_receipt)

    chain = service.reconcile_chain(root, (first,))

    assert chain.latest_lifecycle.status is OrderStatus.CANCELLED
    assert chain.latest_lifecycle.remaining_quantity == Decimal("4")
    assert not chain.can_continue
    assert chain.is_complete
    assert chain.aggregate_remaining_quantity == Decimal("5")



def test_prepare_chain_continuation_uses_authoritative_latest_stage() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
        requested_quantity=Decimal("5"),
    )
    first_receipt = _receipt(first, "2")
    repository = _ReceiptRepository((root_receipt, first_receipt))
    service = _service(repository, first_receipt)

    continuation = service.prepare_chain_continuation(
        root,
        (first,),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh next-stage approval"),
    )

    assert continuation.order.quantity == Decimal("3")
    assert continuation.parent_client_order_id == str(first.order.client_order_id)
    assert continuation.order.client_order_id != first.order.client_order_id
    assert continuation.risk_result.reason == "fresh next-stage approval"


def test_prepare_chain_continuation_respects_requested_quantity() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    repository = _ReceiptRepository((root_receipt,))
    service = _service(repository, root_receipt)

    continuation = service.prepare_chain_continuation(
        root,
        (),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("2"),
    )

    assert continuation.order.quantity == Decimal("2")
    assert continuation.parent_client_order_id == str(root.order.client_order_id)


def test_prepare_chain_continuation_rejects_terminal_latest_stage() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
    )
    first_receipt = _receipt(first, "1")
    terminal_receipt = replace(
        first_receipt,
        outcome=ExecutionOutcome.CANCELLED,
        order_status=OrderStatus.CANCELLED,
        executed_at=first_receipt.executed_at + timedelta(minutes=1),
        fills=(),
        receipt_id=uuid4(),
    )
    repository = _ReceiptRepository((root_receipt, first_receipt, terminal_receipt))
    service = _service(repository, terminal_receipt)

    with pytest.raises(ValueError, match="continuation chain latest lifecycle cannot continue"):
        service.prepare_chain_continuation(
            root,
            (first,),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        )



def test_dispatch_chain_continuation_prepares_and_dispatches_latest_stage() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
        requested_quantity=Decimal("5"),
    )
    first_receipt = _receipt(first, "2")
    next_receipt = _receipt(
        ExecutionLifecycle.rebuild(
            first.order.client_order_id,
            first.order.quantity,
            (first_receipt,),
            correlation_id=str(root.order.client_order_id),
        ).continuation_request(
            first,
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh next-stage approval"),
        ),
        "3",
    )
    repository = _ReceiptRepository((root_receipt, first_receipt))
    port = _PaperPort(next_receipt)
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    result = service.dispatch_chain_continuation(
        root,
        (first,),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh next-stage approval"),
        snapshot=_snapshot(),
    )

    assert result.parent_lifecycle.client_order_id == first.order.client_order_id
    assert result.parent_lifecycle.remaining_quantity == Decimal("3")
    assert result.request.order.quantity == Decimal("3")
    assert result.request.parent_client_order_id == str(first.order.client_order_id)
    assert result.request.order.client_order_id != first.order.client_order_id
    assert result.dispatch.receipt is next_receipt
    assert port.requests == [result.request]


def test_dispatch_chain_continuation_requires_market_snapshot_for_paper() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    repository = _ReceiptRepository((root_receipt,))
    port = _PaperPort(_receipt(root, "6"))
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    with pytest.raises(ValueError, match="requires a market snapshot"):
        service.dispatch_chain_continuation(
            root,
            (),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        )

    assert port.requests == []


def test_dispatch_chain_continuation_rejects_terminal_latest_stage_before_dispatch() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
    )
    first_receipt = _receipt(first, "1")
    terminal_receipt = replace(
        first_receipt,
        outcome=ExecutionOutcome.CANCELLED,
        order_status=OrderStatus.CANCELLED,
        executed_at=first_receipt.executed_at + timedelta(minutes=1),
        fills=(),
        receipt_id=uuid4(),
    )
    repository = _ReceiptRepository((root_receipt, first_receipt, terminal_receipt))
    port = _PaperPort(terminal_receipt)
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    with pytest.raises(ValueError, match="continuation chain latest lifecycle cannot continue"):
        service.dispatch_chain_continuation(
            root,
            (first,),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
            snapshot=_snapshot(),
        )

    assert port.requests == []


def test_dispatch_chain_continuation_and_reconcile_returns_authoritative_child_state() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage one approval"),
        requested_quantity=Decimal("5"),
    )
    first_receipt = _receipt(first, "2")
    prepared = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (first_receipt,),
    ).continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh next-stage approval"),
    )
    child_receipt = _receipt(prepared, "3")
    repository = _ReceiptRepository((root_receipt, first_receipt, child_receipt))
    port = _PaperPort(child_receipt)
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    result = service.dispatch_chain_continuation_and_reconcile(
        root,
        (first,),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh next-stage approval"),
        snapshot=_snapshot(),
    )

    assert isinstance(result, ExecutionContinuationDispatchReconciliation)
    assert result.parent_lifecycle.client_order_id == first.order.client_order_id
    assert result.parent_lifecycle.remaining_quantity == Decimal("3")
    assert result.request.order.quantity == Decimal("3")
    assert result.request.parent_client_order_id == str(first.order.client_order_id)
    assert result.dispatch.receipt is child_receipt
    assert result.child_lifecycle.client_order_id == result.request.order.client_order_id
    assert result.child_lifecycle.status is OrderStatus.FILLED
    assert result.child_lifecycle.filled_quantity == Decimal("3")
    assert result.dispatch_performed is False
    assert port.requests == []


def test_dispatch_chain_continuation_and_reconcile_rejects_missing_authoritative_child() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    repository = _ReceiptRepository((root_receipt,))
    prepared = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(prepared, "6")
    port = _PaperPort(child_receipt)
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    with pytest.raises(ValueError, match="continuation receipt evidence"):
        service.dispatch_chain_continuation_and_reconcile(
            root,
            (),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
            snapshot=_snapshot(),
        )

    assert port.requests


def test_dispatch_chain_continuation_reuses_existing_authoritative_child() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    )
    existing_child = parent_lifecycle.continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    authoritative_child_receipt = _receipt(existing_child, "3")
    duplicate_dispatch_receipt = _receipt(existing_child, "6")
    repository = _ReceiptRepository((root_receipt, authoritative_child_receipt))
    port = _PaperPort(duplicate_dispatch_receipt)
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    result = service.dispatch_chain_continuation(
        root,
        (),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=_snapshot(),
    )

    assert result.dispatch_performed is False
    assert result.dispatch.receipt is authoritative_child_receipt
    assert result.parent_lifecycle.client_order_id == root.order.client_order_id
    assert result.request.order.client_order_id == existing_child.order.client_order_id
    assert result.request.order.quantity == Decimal("6")
    assert port.requests == []


class _BlockingRecordingPaperPort(_PaperPort):
    def __init__(self, receipt, repository) -> None:
        super().__init__(receipt)
        self._repository = repository
        self.started = Event()
        self.release = Event()
        self._lock = Lock()

    def execute(self, request, *, snapshot):
        with self._lock:
            self.requests.append(request)
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test dispatch release timed out")
        self._repository.save(self.receipt)
        return self.receipt


def test_concurrent_chain_continuation_dispatch_has_one_atomic_claim() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    )
    child = parent_lifecycle.continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("6"),
    )
    child_receipt = _receipt(child, "6")
    repository = _ReceiptRepository((root_receipt,))
    port = _BlockingRecordingPaperPort(child_receipt, repository)
    idempotency = InMemoryIdempotencyStore()
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(
        lifecycle,
        dispatcher,
        idempotency_store=idempotency,
    )

    def dispatch():
        return service.dispatch_chain_continuation(
            root,
            (),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
            snapshot=_snapshot(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(dispatch)
        assert port.started.wait(timeout=2)
        second_future = executor.submit(dispatch)

        with pytest.raises(
            ValueError,
            match="continuation dispatch is already pending and requires reconciliation",
        ):
            second_future.result(timeout=2)

        port.release.set()
        first = first_future.result(timeout=2)

    assert first.dispatch_performed
    assert first.dispatch.receipt is child_receipt
    assert len(port.requests) == 1


def test_pending_continuation_claim_is_resolved_from_authoritative_child() -> None:
    root = _request()
    root_receipt = _receipt(root, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    )
    child = parent_lifecycle.continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("6"),
    )
    child_receipt = _receipt(child, "6")
    repository = _ReceiptRepository((root_receipt, child_receipt))
    idempotency = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(child)
    idempotency.reserve_or_get(child.order.client_order_id, fingerprint)
    port = _PaperPort(_receipt(child, "6"))
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    service = ExecutionContinuationService(
        lifecycle,
        dispatcher,
        idempotency_store=idempotency,
    )

    result = service.dispatch_chain_continuation(
        root,
        (),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=_snapshot(),
    )

    assert not result.dispatch_performed
    assert result.dispatch.receipt is child_receipt
    assert port.requests == []
    assert idempotency.check(
        child.order.client_order_id,
        fingerprint,
    ).existing_receipt_id == child_receipt.receipt_id
