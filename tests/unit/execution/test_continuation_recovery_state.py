from decimal import Decimal

from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import (
    ExecutionContinuationService,
    PendingContinuationRecoveryState,
)
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.idempotency import InMemoryIdempotencyStore, request_fingerprint
from quantx.execution.lifecycle import ExecutionLifecycleService
from quantx.execution.receipts.lifecycle import ExecutionLifecycle

from .test_continuation import _PaperPort, _ReceiptRepository, _receipt, _request


def _pending_service(repository, receipt, store):
    dispatcher = ExecutionDispatcher(paper_port=_PaperPort(receipt))
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    return ExecutionContinuationService(
        lifecycle,
        dispatcher,
        idempotency_store=store,
    )


def test_inspect_pending_continuation_reports_pending_without_authoritative_evidence():
    root = _request()
    root_receipt = _receipt(root, "4")
    child = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    store = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(child)
    store.reserve_or_get(child.order.client_order_id, fingerprint)
    service = _pending_service(
        _ReceiptRepository((root_receipt,)),
        _receipt(child, "6"),
        store,
    )

    status = service.inspect_pending_continuation(root, child)

    assert status.state is PendingContinuationRecoveryState.PENDING
    assert status.receipt_id is None


def test_inspect_pending_continuation_reports_recoverable_evidence():
    root = _request()
    root_receipt = _receipt(root, "4")
    child = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(child, "6")
    store = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(child)
    store.reserve_or_get(child.order.client_order_id, fingerprint)
    service = _pending_service(
        _ReceiptRepository((root_receipt, child_receipt)),
        child_receipt,
        store,
    )

    status = service.inspect_pending_continuation(root, child)

    assert status.state is PendingContinuationRecoveryState.RECOVERABLE
    assert status.receipt_id == child_receipt.receipt_id
    assert store.check(child.order.client_order_id, fingerprint).reservation_pending


def test_inspect_pending_continuation_reports_resolved_claim():
    root = _request()
    root_receipt = _receipt(root, "4")
    child = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (root_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(child, "6")
    store = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(child)
    store.reserve_or_get(child.order.client_order_id, fingerprint)
    store.complete(
        child.order.client_order_id,
        fingerprint,
        child_receipt.receipt_id,
    )
    service = _pending_service(
        _ReceiptRepository((root_receipt, child_receipt)),
        child_receipt,
        store,
    )

    status = service.inspect_pending_continuation(root, child)

    assert status.state is PendingContinuationRecoveryState.RESOLVED
    assert status.receipt_id == child_receipt.receipt_id
