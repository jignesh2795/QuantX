from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.dispatch import ExecutionDispatcher
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument() -> Instrument:
    market = _market()
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _snapshot(instrument: InstrumentId | None = None) -> MarketSnapshot:
    instrument = instrument or InstrumentId("NSE", "TCS")
    timestamp = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    return Quote(
        instrument,
        timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )


def _request(
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=(
            BrokerConnectionId("conn-1") if mode is ExecutionMode.LIVE else None
        ),
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        required_margin=Decimal("100"),
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    policy = (
        PolicyResult(PolicyDecision.APPROVE, "approved")
        if mode is ExecutionMode.LIVE
        else None
    )
    return ApprovedExecutionRequest(
        order=order,
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=policy,
    )


def _receipt(request: ApprovedExecutionRequest, *, source: str) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=request.order.created_at,
        source=source,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
    )


class FakePaperPort:
    def __init__(self) -> None:
        self.calls: list[tuple[ApprovedExecutionRequest, MarketSnapshot]] = []

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        self.calls.append((request, snapshot))
        return _receipt(request, source="fake-paper")


class FakeLivePort:
    def __init__(self) -> None:
        self.calls: list[ApprovedExecutionRequest] = []

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        self.calls.append(request)
        return _receipt(request, source="fake-live")

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return _receipt(request, source="fake-live-cancel")

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return _receipt(request, source="fake-live-reconcile")


def test_dispatch_routes_paper_mode_with_market_snapshot() -> None:
    port = FakePaperPort()
    request = _request()
    result = ExecutionDispatcher(paper_port=port).dispatch(
        request,
        snapshot=_snapshot(),
    )

    assert result.request is request
    assert result.receipt.source == "fake-paper"
    assert port.calls == [(request, _snapshot())]


@pytest.mark.parametrize("mode", [ExecutionMode.SHADOW, ExecutionMode.REPLAY])
def test_dispatch_routes_simulated_modes_to_paper_port(mode: ExecutionMode) -> None:
    port = FakePaperPort()
    request = _request(mode)

    result = ExecutionDispatcher(paper_port=port).dispatch(
        request,
        snapshot=_snapshot(),
    )

    assert result.receipt.source == "fake-paper"
    assert port.calls[0][0] is request


def test_dispatch_routes_live_mode_to_live_port() -> None:
    port = FakeLivePort()
    request = _request(ExecutionMode.LIVE)

    result = ExecutionDispatcher(live_port=port).dispatch(request)

    assert result.request is request
    assert result.receipt.source == "fake-live"
    assert port.calls == [request]


def test_dispatch_requires_snapshot_for_simulated_modes() -> None:
    with pytest.raises(ValueError, match="market snapshot"):
        ExecutionDispatcher(paper_port=FakePaperPort()).dispatch(_request())


def test_dispatch_rejects_snapshot_for_wrong_instrument() -> None:
    with pytest.raises(ValueError, match="instrument"):
        ExecutionDispatcher(paper_port=FakePaperPort()).dispatch(
            _request(),
            snapshot=_snapshot(InstrumentId("NSE", "INFY")),
        )


def test_dispatch_requires_matching_adapter() -> None:
    with pytest.raises(ValueError, match="no paper execution adapter"):
        ExecutionDispatcher().dispatch(_request(), snapshot=_snapshot())

    with pytest.raises(ValueError, match="no live execution adapter"):
        ExecutionDispatcher().dispatch(_request(ExecutionMode.LIVE))


def test_dispatch_does_not_execute_backtest_mode() -> None:
    request = _request(ExecutionMode.BACKTEST)

    with pytest.raises(ValueError, match="not dispatchable"):
        ExecutionDispatcher(
            paper_port=FakePaperPort(),
            live_port=FakeLivePort(),
        ).dispatch(request)


def test_dispatch_preserves_account_and_connection_on_live_receipt() -> None:
    request = _request(ExecutionMode.LIVE)
    result = ExecutionDispatcher(live_port=FakeLivePort()).dispatch(request)

    assert result.receipt.account_id == AccountId("acct-1")
    assert result.receipt.connection_id == BrokerConnectionId("conn-1")
