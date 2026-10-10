from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import (
    ExecutionContinuationReconciliation,
    ExecutionContinuationService,
)
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.lifecycle import ExecutionLifecycleService
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt

from .test_continuation import _PaperPort, _ReceiptRepository, _receipt, _request


def _service(repository: _ReceiptRepository, receipt) -> ExecutionContinuationService:
    dispatcher = ExecutionDispatcher(paper_port=_PaperPort(receipt))
    lifecycle_service = ExecutionLifecycleService(
        dispatcher,
        receipt_repository=repository,
    )
    return ExecutionContinuationService(lifecycle_service, dispatcher)


def test_reconcile_continuation_rebuilds_parent_and_child_independently() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(child_request, "3")
    service = _service(
        _ReceiptRepository((parent_receipt, child_receipt)),
        child_receipt,
    )

    result = service.reconcile_continuation(parent_request, child_request)

    assert isinstance(result, ExecutionContinuationReconciliation)
    assert result.parent_lifecycle.filled_quantity == Decimal("4")
    assert result.parent_lifecycle.remaining_quantity == Decimal("6")
    assert result.child_lifecycle.client_order_id == child_request.order.client_order_id
    assert result.child_lifecycle.filled_quantity == Decimal("3")
    assert result.child_lifecycle.status is OrderStatus.PARTIALLY_FILLED
    assert result.aggregate_filled_quantity == Decimal("7")
    assert result.aggregate_remaining_quantity == Decimal("3")


def test_reconcile_continuation_deduplicates_child_receipts() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    child_receipt = _receipt(child_request, "6", receipt_id=uuid4())
    service = _service(
        _ReceiptRepository((parent_receipt, child_receipt, child_receipt)),
        child_receipt,
    )

    result = service.reconcile_continuation(parent_request, child_request)

    assert result.child_lifecycle.filled_quantity == Decimal("6")
    assert result.aggregate_filled_quantity == Decimal("10")
    assert result.aggregate_remaining_quantity == Decimal("0")


def test_reconcile_continuation_rejects_wrong_parent_relationship() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    wrong_parent_request = _request()
    service = _service(
        _ReceiptRepository((parent_receipt,)),
        parent_receipt,
    )

    with pytest.raises(ValueError, match="does not reference the parent"):
        service.reconcile_continuation(wrong_parent_request, child_request)


def test_reconcile_continuation_rejects_missing_child_evidence() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "4")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    service = _service(_ReceiptRepository((parent_receipt,)), parent_receipt)

    with pytest.raises(ValueError, match="continuation receipt evidence"):
        service.reconcile_continuation(parent_request, child_request)


def test_reconcile_continuation_rejects_child_quantity_above_parent_remainder() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "9")
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    valid_child = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    oversized_child = valid_child.__class__(
        order=valid_child.order.__class__(
            instrument=valid_child.order.instrument,
            side=valid_child.order.side,
            order_type=valid_child.order.order_type,
            quantity=Decimal("2"),
            limit_price=valid_child.order.limit_price,
            stop_price=valid_child.order.stop_price,
            time_in_force=valid_child.order.time_in_force,
            intent_id=valid_child.order.intent_id,
            client_order_id=valid_child.order.client_order_id,
            strategy_id=valid_child.order.strategy_id,
            strategy_version=valid_child.order.strategy_version,
            required_capabilities=valid_child.order.required_capabilities,
        ),
        execution_context=valid_child.execution_context,
        risk_result=valid_child.risk_result,
        policy_result=valid_child.policy_result,
        required_margin=valid_child.required_margin,
        parent_client_order_id=valid_child.parent_client_order_id,
    )
    child_receipt = _receipt(oversized_child, "1")
    service = _service(
        _ReceiptRepository((parent_receipt, child_receipt)),
        child_receipt,
    )

    with pytest.raises(ValueError, match="continuation request exceeds parent lifecycle remainder"):
        service.reconcile_continuation(parent_request, oversized_child)


def test_reconcile_continuation_rejects_terminal_parent_with_remaining_quantity() -> None:
    parent_request = _request()
    partial_receipt = _receipt(parent_request, "4")
    cancelled_receipt = ExecutionReceipt.from_order(
        parent_request.order,
        request_id=uuid4(),
        outcome=ExecutionOutcome.CANCELLED,
        order_status=OrderStatus.CANCELLED,
        executed_at=datetime(2026, 1, 1, 9, 16, tzinfo=UTC),
        correlation_id=parent_request.correlation_id,
    )
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (partial_receipt, cancelled_receipt),
    )
    assert parent_lifecycle.status is OrderStatus.CANCELLED
    assert parent_lifecycle.remaining_quantity == Decimal("6")

    partial_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (partial_receipt,),
    )
    child_request = partial_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )

    child_receipt = _receipt(child_request, "1")
    service = _service(
        _ReceiptRepository((partial_receipt, cancelled_receipt, child_receipt)),
        child_receipt,
    )

    with pytest.raises(ValueError, match="continuation parent lifecycle cannot continue"):
        service.reconcile_continuation(parent_request, child_request)
