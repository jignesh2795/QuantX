from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import OrderStatus
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.execution_adapter import BrokerExecutionAdapter


class FakeSubmission:
    def __init__(self, receipt: ExecutionReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def submit(self, request) -> ExecutionReceipt:
        self.calls += 1
        return self.receipt

    def cancel(self, request) -> ExecutionReceipt:
        return self.receipt

    def reconcile(self, request) -> ExecutionReceipt:
        return self.receipt


def test_broker_execution_adapter_delegates_to_submission_plugin() -> None:
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime.now(UTC),
    )
    submission = FakeSubmission(receipt)
    adapter = BrokerExecutionAdapter(submission)

    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.PAPER,
    )
    request = ApprovedExecutionRequest(
        order=build_order_from_intent(
            TradeIntent(
                instrument=instrument.instrument_id,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                order_type=OrderType.MARKET,
                execution_context=context,
            )
        ),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )
    result = adapter.execute(request)

    assert result is receipt
    assert submission.calls == 1


def test_broker_execution_adapter_rejects_direct_live_execution() -> None:
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime.now(UTC),
    )
    submission = FakeSubmission(receipt)
    adapter = BrokerExecutionAdapter(submission)

    request = SimpleNamespace(execution_context=SimpleNamespace(execution_mode=ExecutionMode.LIVE))
    with pytest.raises(ValueError, match="ExecutionOrchestrator.*UnitOfWork"):
        adapter.execute(request)  # type: ignore[arg-type]

    assert submission.calls == 0
