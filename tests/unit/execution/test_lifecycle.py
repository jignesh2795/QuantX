from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.deployment import ExecutionContext, ExecutionMode, MarketContext
from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Quote
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.lifecycle import ExecutionLifecycleService
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.domain.orders import Fill, Order


def _request(quantity: str = "10") -> ApprovedExecutionRequest:
    instrument = InstrumentRegistry.reference_instrument()
    order = Order(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        time_in_force=TimeInForce.DAY,
        required_capabilities=("market_order",),
    )
    context = ExecutionContext(
        account_id="account-1",
        portfolio_id="portfolio-1",
        deployment_id="deployment-1",
        market=MarketContext(venue=instrument.venue, segment=instrument.segment),
        execution_mode=ExecutionMode.PAPER,
    )
    return ApprovedExecutionRequest(
        order=order,
        execution_context=context,
        risk_result=RiskResult(
            decision=RiskDecision.APPROVE,
            reasons=(),
        ),
        policy_result=PolicyResult(approved=True, reasons=()),
    )


def _receipt(request: ApprovedExecutionRequest, quantity: str) -> ExecutionReceipt:
    now = datetime.now(timezone.utc)
    fill = Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal(quantity),
        price=Decimal("100"),
        filled_at=now,
    )
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        order_status=OrderStatus.PARTIALLY_FILLED,
        executed_at=now,
        fills=(fill,),
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        correlation_id=str(request.order.client_order_id),
    )


class _PaperPort:
    def __init__(self, receipt: ExecutionReceipt) -> None:
        self.receipt = receipt

    def execute(self, request: ApprovedExecutionRequest, *, snapshot: MarketSnapshot):
        return self.receipt


class _ReceiptRepository:
    def __init__(self, receipts: tuple[ExecutionReceipt, ...]) -> None:
        self.receipts = receipts

    def save(self, receipt):
        self.receipts = (*self.receipts, receipt)

    def get(self, receipt_id):
        return next((r for r in self.receipts if r.receipt_id == receipt_id), None)

    def get_by_client_order(self, client_order_id):
        return next(
            (r for r in self.receipts if r.client_order_id == client_order_id),
            None,
        )

    def list_by_correlation_id(self, correlation_id):
        return tuple(
            r for r in self.receipts
            if r.correlation_id == str(correlation_id)
            or r.client_order_id == correlation_id
        )


def test_dispatch_returns_lifecycle_from_receipt() -> None:
    request = _request()
    receipt = _receipt(request, "4")
    dispatcher = ExecutionDispatcher(paper_port=_PaperPort(receipt))
    service = ExecutionLifecycleService(dispatcher)

    result = service.dispatch(
        request,
        snapshot=Quote(
            instrument=request.order.instrument,
            timestamp=datetime.now(timezone.utc),
            last=Decimal("100"),
        ),
    )

    assert result.dispatch.receipt == receipt
    assert result.lifecycle.client_order_id == request.order.client_order_id
    assert result.lifecycle.order_quantity == Decimal("10")
    assert result.lifecycle.filled_quantity == Decimal("4")
    assert result.lifecycle.status is OrderStatus.PARTIALLY_FILLED
    assert result.lifecycle.can_continue


def test_reconcile_rebuilds_from_authoritative_receipts() -> None:
    request = _request()
    first = _receipt(request, "4")
    second = _receipt(request, "6")
    repository = _ReceiptRepository((first, second))
    service = ExecutionLifecycleService(
        ExecutionDispatcher(paper_port=_PaperPort(first)),
        receipt_repository=repository,
    )

    lifecycle = service.reconcile(request)

    assert lifecycle.filled_quantity == Decimal("10")
    assert lifecycle.status is OrderStatus.FILLED
    assert lifecycle.is_complete
    assert not lifecycle.can_continue


def test_dispatch_prefers_authoritative_receipt_history() -> None:
    request = _request()
    first = _receipt(request, "4")
    second = _receipt(request, "2")
    repository = _ReceiptRepository((first, second))
    service = ExecutionLifecycleService(
        ExecutionDispatcher(paper_port=_PaperPort(first)),
        receipt_repository=repository,
    )

    result = service.dispatch(
        request,
        snapshot=Quote(
            instrument=request.order.instrument,
            timestamp=datetime.now(timezone.utc),
            last=Decimal("100"),
        ),
    )

    assert result.lifecycle.filled_quantity == Decimal("6")
    assert result.lifecycle.status is OrderStatus.PARTIALLY_FILLED


def test_reconcile_requires_authoritative_repository() -> None:
    request = _request()
    service = ExecutionLifecycleService(ExecutionDispatcher())

    with pytest.raises(ValueError, match="authoritative receipt repository"):
        service.reconcile(request)


def test_reconcile_rejects_missing_receipt_evidence() -> None:
    request = _request()
    repository = _ReceiptRepository(())
    service = ExecutionLifecycleService(
        ExecutionDispatcher(),
        receipt_repository=repository,
    )

    with pytest.raises(ValueError, match="receipts are unavailable"):
        service.reconcile(request)
