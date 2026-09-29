from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import (
    ExecutionContinuationService,
    PendingContinuationRecoveryState,
)
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.idempotency import InMemoryIdempotencyStore, request_fingerprint
from quantx.execution.lifecycle import ExecutionLifecycleService
from quantx.execution.receipts.models import ExecutionOutcome
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


def test_inspect_pending_chain_continuation_reports_latest_stage_as_recoverable() -> None:
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
    second = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (first_receipt,),
    ).continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage two approval"),
    )
    second_receipt = _receipt(second, "3")
    store = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(second)
    store.reserve_or_get(second.order.client_order_id, fingerprint)
    service = _pending_service(
        _ReceiptRepository((root_receipt, first_receipt, second_receipt)),
        second_receipt,
        store,
    )

    status = service.inspect_pending_chain_continuation(
        root,
        (first,),
        second,
    )

    assert status.state is PendingContinuationRecoveryState.RECOVERABLE
    assert status.receipt_id == second_receipt.receipt_id


def test_inspect_pending_chain_continuation_fails_closed_before_state_resolution() -> None:
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
    child = ExecutionLifecycle.rebuild(
        first.order.client_order_id,
        first.order.quantity,
        (first_receipt,),
    ).continuation_request(
        first,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh stage two approval"),
    )
    store = InMemoryIdempotencyStore()
    fingerprint = request_fingerprint(child)
    store.reserve_or_get(child.order.client_order_id, fingerprint)
    service = _pending_service(
        _ReceiptRepository((root_receipt, first_receipt, terminal_receipt)),
        child,
        store,
    )

    with pytest.raises(ValueError, match="chain stage lifecycle cannot continue"):
        service.inspect_pending_chain_continuation(
            root,
            (first, child),
            child,
        )

    decision = store.check(child.order.client_order_id, fingerprint)
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None
