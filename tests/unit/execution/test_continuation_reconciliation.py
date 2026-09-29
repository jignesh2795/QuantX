from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import ExecutionContinuationReconciliation
from quantx.execution.receipts.lifecycle import ExecutionLifecycle

from .test_continuation import (
    _PaperPort,
    _ReceiptRepository,
    _receipt,
    _request,
    _service,
)


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
    repository = _ReceiptRepository((parent_receipt, child_receipt))
    port = _PaperPort(child_receipt)
    service = _service(parent_request, parent_receipt, port)
    service._lifecycle_service._receipt_repository = repository

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
    repository = _ReceiptRepository((parent_receipt, child_receipt, child_receipt))
    service = _service(parent_request, parent_receipt, _PaperPort(child_receipt))
    service._lifecycle_service._receipt_repository = repository

    result = service.reconcile_continuation(parent_request, child_request)

    assert result.child_lifecycle.filled_quantity == Decimal("6")
    assert result.aggregate_filled_quantity == Decimal("10")
    assert result.aggregate_remaining_quantity == Decimal("0")


def test_reconcile_continuation_rejects_unrelated_child() -> None:
    parent_request = _request()
    parent_receipt = _receipt(parent_request, "4")
    other_request = _request()
    parent_lifecycle = ExecutionLifecycle.rebuild(
        parent_request.order.client_order_id,
        parent_request.order.quantity,
        (parent_receipt,),
    )
    child_request = parent_lifecycle.continuation_request(
        parent_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    unrelated_child = parent_lifecycle.continuation_request(
        other_request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    service = _service(parent_request, parent_receipt, _PaperPort(child_request and parent_receipt))
    repository = _ReceiptRepository((parent_receipt, _receipt(unrelated_child, "6")))
    service._lifecycle_service._receipt_repository = repository

    with pytest.raises(ValueError, match="does not reference the parent"):
        service.reconcile_continuation(parent_request, unrelated_child)
