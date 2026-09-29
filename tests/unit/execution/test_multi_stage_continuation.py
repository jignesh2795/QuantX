from decimal import Decimal

import pytest

from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.continuation import ExecutionContinuationChain
from quantx.execution.receipts.lifecycle import ExecutionLifecycle

from .test_continuation import _PaperPort, _ReceiptRepository, _receipt, _request
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
    first_receipt = _receipt(root, "8")
    first = ExecutionLifecycle.rebuild(
        root.order.client_order_id,
        root.order.quantity,
        (first_receipt,),
    ).continuation_request(
        root,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
    )
    second = second = first.__class__(
        order=first.order.__class__(
            instrument=first.order.instrument,
            side=first.order.side,
            order_type=first.order.order_type,
            quantity=Decimal("5"),
            limit_price=first.order.limit_price,
            stop_price=first.order.stop_price,
            time_in_force=first.order.time_in_force,
            intent_id=first.order.intent_id,
            client_order_id=ExecutionLifecycle.rebuild(
                first.order.client_order_id,
                first.order.quantity,
                (first_receipt,),
            ).continuation_client_order_id(Decimal("5")),
            strategy_id=first.order.strategy_id,
            strategy_version=first.order.strategy_version,
            required_capabilities=first.order.required_capabilities,
        ),
        execution_context=first.execution_context,
        risk_result=first.risk_result,
        policy_result=first.policy_result,
        required_margin=first.required_margin,
        parent_client_order_id=str(first.order.client_order_id),
    )
    repository = _ReceiptRepository((first_receipt,))
    service = _service(repository, first_receipt)

    with pytest.raises(ValueError, match="exceeds parent lifecycle remainder"):
        service.reconcile_chain(root, (first, second))
