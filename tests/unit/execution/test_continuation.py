from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Quote
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.orders import Fill, Order
from quantx.execution.continuation import ExecutionContinuationService
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.lifecycle import ExecutionLifecycleService
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _request(quantity: str = "10") -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    order = Order(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        time_in_force=TimeInForce.DAY,
        required_capabilities=("market_order",),
    )
    return ApprovedExecutionRequest(
        order=order,
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _receipt(
    request: ApprovedExecutionRequest,
    quantity: str,
    *,
    receipt_id=None,
) -> ExecutionReceipt:
    now = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
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
        receipt_id=receipt_id or uuid4(),
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
        correlation_id=request.correlation_id,
    )


def _snapshot() -> MarketSnapshot:
    request = _request()
    return Quote(
        request.order.instrument,
        datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        last=Decimal("100"),
    )


class _PaperPort:
    def __init__(self, receipt: ExecutionReceipt) -> None:
        self.receipt = receipt
        self.requests = []

    def execute(self, request: ApprovedExecutionRequest, *, snapshot: MarketSnapshot):
        self.requests.append(request)
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
            r
            for r in self.receipts
            if r.correlation_id == str(correlation_id) or r.client_order_id == correlation_id
        )


def _service(request: ApprovedExecutionRequest, receipt: ExecutionReceipt, port: _PaperPort):
    repository = _ReceiptRepository((receipt,))
    dispatcher = ExecutionDispatcher(paper_port=port)
    lifecycle = ExecutionLifecycleService(dispatcher, receipt_repository=repository)
    return ExecutionContinuationService(lifecycle, dispatcher)


def test_continuation_uses_authoritative_remainder_and_fresh_identity() -> None:
    request = _request()
    parent_receipt = _receipt(request, "4")
    port = _PaperPort(_receipt(request, "6"))
    service = _service(request, parent_receipt, port)

    result = service.continue_partial(
        request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=_snapshot(),
    )

    assert result.parent_lifecycle.filled_quantity == Decimal("4")
    assert result.parent_lifecycle.remaining_quantity == Decimal("6")
    assert result.request.order.quantity == Decimal("6")
    assert result.request.parent_client_order_id == str(request.order.client_order_id)
    assert result.request.order.client_order_id != request.order.client_order_id
    assert result.request.risk_result.reason == "fresh approval"
    assert result.dispatch.receipt == port.receipt
    assert port.requests == [result.request]


def test_continuation_can_request_less_than_remainder() -> None:
    request = _request()
    receipt = _receipt(request, "4")
    port = _PaperPort(_receipt(request, "2"))
    service = _service(request, receipt, port)

    result = service.continue_partial(
        request,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        requested_quantity=Decimal("2"),
        snapshot=_snapshot(),
    )

    assert result.request.order.quantity == Decimal("2")
    assert result.parent_lifecycle.remaining_quantity == Decimal("6")


def test_continuation_rejects_stale_or_unapproved_risk() -> None:
    request = _request()
    receipt = _receipt(request, "4")
    port = _PaperPort(_receipt(request, "6"))
    service = _service(request, receipt, port)

    with pytest.raises(ValueError, match="fresh approved risk"):
        service.continue_partial(
            request,
            risk_result=RiskResult(RiskDecision.REJECT, "stale approval"),
            snapshot=_snapshot(),
        )
    assert port.requests == []


def test_continuation_rejects_when_parent_is_complete() -> None:
    request = _request()
    receipt = _receipt(request, "10")
    port = _PaperPort(_receipt(request, "10"))
    service = _service(request, receipt, port)

    with pytest.raises(ValueError, match="no remaining"):
        service.continue_partial(
            request,
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
            snapshot=_snapshot(),
        )
    assert port.requests == []


def test_continuation_requires_authoritative_reconciliation() -> None:
    request = _request()
    dispatcher = ExecutionDispatcher()
    lifecycle = ExecutionLifecycleService(dispatcher)
    service = ExecutionContinuationService(lifecycle, dispatcher)

    with pytest.raises(ValueError, match="authoritative receipt repository"):
        service.continue_partial(
            request,
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        )
