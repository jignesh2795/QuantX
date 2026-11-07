"""End-to-end offline PAPER/BACKTEST integration for declarative Flow strategies."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.backtest import (
    BacktestDisposition,
    BacktestResult,
    DeterministicBacktestService,
)
from quantx.application.strategy_rehearsal import RehearsalInput, StrategyRehearsalSession
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import (
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.orders import Fill
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import (
    ExecutionPolicyEngine,
    PolicyContext,
    PolicyDecision,
    PolicyResult,
)
from quantx.domain.risk import RiskDecision
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.profile import ExecutionProfile, SlippageModel
from quantx.markets import default_market_registry
from quantx.markets.india.market_pack import (
    INDIA_EQUITY_POSITION_EFFECT_POLICY,
    INDIA_EQUITY_PRODUCT_SELECTION,
)
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.strategy.context import StrategyContext
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.flow import (
    FlowCompiler,
    FlowDefinition,
    FlowEdge,
    FlowExecutableStrategy,
    FlowExecutionPlan,
    FlowNode,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry
from quantx.strategy.runtime import ExecutableStrategy

_NOW = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
_STRATEGY_ID = StrategyId("flow-offline-integration")
_VERSION = "1"


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _ir() -> StrategyIR:
    return StrategyIR(
        strategy_id=_STRATEGY_ID,
        version=_VERSION,
        name="Flow offline integration",
        market_contexts=(),
        parameters=(),
    )


def _deployment() -> StrategyDeployment:
    return StrategyDeployment(
        deployment_id=StrategyDeploymentId("flow-paper-deployment"),
        strategy_id=_STRATEGY_ID.value,
        strategy_version=_VERSION,
        portfolio_id=PortfolioId("flow-paper-portfolio"),
        account_id=AccountId("flow-paper-account"),
        market=_market(),
        execution_mode=ExecutionMode.PAPER,
        enabled=True,
    )


def _execution_context() -> ExecutionContext:
    deployment = _deployment()
    return ExecutionContext(
        account_id=deployment.account_id,
        portfolio_id=deployment.portfolio_id,
        deployment_id=deployment.deployment_id,
        market=deployment.market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _financial_state(
    capital_source: CapitalSourceType = CapitalSourceType.PAPER_CONFIGURED,
) -> AccountFinancialState:
    return AccountFinancialState(
        capital_source,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _event() -> MarketDataEvent:
    instrument = _instrument().instrument_id
    quote = Quote(
        instrument=instrument,
        timestamp=_NOW,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return MarketDataEvent(
        data_type=MarketDataType.QUOTE,
        timestamp=_NOW,
        instrument=instrument,
        payload=quote,
    )


def _market_snapshot() -> MarketSnapshot:
    return MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5"))


def _history() -> HistoricalDataSeries:
    quote = _event().payload
    assert isinstance(quote, Quote)
    return HistoricalDataSeries(
        (HistoricalObservation(quote, "flow-offline-test", "1", 0, dataset_id="nse-eq"),)
    )


class _CountingAccounting(FillAccounting):
    def __init__(self) -> None:
        super().__init__()
        self.applications: list[Fill] = []

    def apply(
        self,
        fill: Fill,
        *,
        fee: Decimal = Decimal("0"),
    ) -> PositionLedgerEntry:
        self.applications.append(fill)
        return super().apply(fill, fee=fee)


def _paper_executor(accounting: _CountingAccounting) -> PaperOrderExecutor:
    profile = ExecutionProfile(
        profile_id="flow-offline",
        version="1",
        slippage_model=SlippageModel.NONE,
        fee_rate=Decimal("0"),
    )
    return PaperOrderExecutor(PaperBroker(profile), accounting)


def _flow_plan(
    *,
    action: str = "BUY",
    side: str | None = "BUY",
    quantity: str = "2",
) -> FlowExecutionPlan:
    nodes = [
        FlowNode("action", "signal_action_constant", (("value", action),)),
        FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        FlowNode("reason", "string_constant", (("value", "offline Flow decision"),)),
        FlowNode("result", "strategy_result"),
    ]
    edges = [
        FlowEdge("result-action", "action", "value", "result", "action"),
        FlowEdge("result-confidence", "confidence", "value", "result", "confidence"),
        FlowEdge("result-reason", "reason", "value", "result", "reason"),
    ]
    if side is not None:
        nodes.extend(
            (
                FlowNode("intent", "trade_intent", (
                    ("order_type", "MARKET"),
                    ("side", side),
                    ("time_in_force", "DAY"),
                )),
                FlowNode("quantity", "decimal_constant", (("value", quantity),)),
            )
        )
        edges.extend(
            (
                FlowEdge("quantity-intent", "quantity", "value", "intent", "quantity"),
                FlowEdge("result-intent", "intent", "intent", "result", "intent"),
            )
        )
    definition = FlowDefinition(
        strategy_id=_STRATEGY_ID,
        version=_VERSION,
        name="Flow offline integration",
        nodes=tuple(nodes),
        edges=tuple(edges),
        market_contexts=(_market(),),
    )
    return FlowCompiler().compile(definition)


def _registry(plan: FlowExecutionPlan) -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(
        _STRATEGY_ID.value,
        _VERSION,
        lambda: FlowExecutableStrategy(plan),
    )
    return registry


def _rehearsal_session(
    plan: FlowExecutionPlan,
    *,
    accounting: _CountingAccounting | None = None,
    deployment: StrategyDeployment | None = None,
    policy_engine: ExecutionPolicyEngine | None = None,
    instrument_registry: InMemoryInstrumentRegistry | None = None,
) -> tuple[StrategyRehearsalSession, _CountingAccounting]:
    held = accounting or _CountingAccounting()
    session = StrategyRehearsalSession(
        registry=_registry(plan),
        strategy_ir=_ir(),
        deployment=deployment or _deployment(),
        instrument_registry=instrument_registry or InMemoryInstrumentRegistry((_instrument(),)),
        paper_executor=_paper_executor(held),
        financial_state=_financial_state(),
        policy_engine=policy_engine,
        product_selection=INDIA_EQUITY_PRODUCT_SELECTION,
        position_effect_policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
    )
    return session, held


def _backtest(
    plan: FlowExecutionPlan,
    *,
    strategy: ExecutableStrategy | None = None,
) -> BacktestResult:
    registry = _registry(plan)
    strategy_instance = strategy or registry.resolve(_ir())
    service = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        product_selection=INDIA_EQUITY_PRODUCT_SELECTION,
        position_effect_policy=INDIA_EQUITY_POSITION_EFFECT_POLICY,
    )
    result = service.run(
        series=_history(),
        strategy=StrategyEvaluationService(strategy_instance),
        strategy_ir=_ir(),
        execution_context=_execution_context(),
        financial_state=_financial_state(CapitalSourceType.BACKTEST_CONFIGURED),
        market_registry=default_market_registry(),
    )
    return result


@pytest.mark.parametrize(
    ("action", "side"),
    [("BUY", "BUY"), ("SELL", "SELL")],
)
def test_flow_paper_rehearsal_uses_deployment_preparation_risk_policy_and_paper(
    action: str,
    side: str,
) -> None:
    plan = _flow_plan(action=action, side=side)
    session, accounting = _rehearsal_session(plan)

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.evaluation is not None
    assert step.evaluation.result.signal.action is (
        SignalAction.BUY if action == "BUY" else SignalAction.SELL
    )
    assert step.evaluation.result.signal.generated_at == _NOW
    assert step.evaluation.result.intent is not None
    assert step.evaluation.result.intent.side is (
        OrderSide.BUY if side == "BUY" else OrderSide.SELL
    )
    assert step.evaluation.result.intent.quantity == Decimal("2")
    assert step.preparation is not None
    assert step.preparation.risk_result is not None
    assert step.preparation.risk_result.decision is RiskDecision.APPROVE
    assert step.preparation.policy_result is not None
    assert step.preparation.policy_result.approved
    assert step.preparation.request is not None
    assert step.preparation.request.execution_context == _execution_context()
    assert step.preparation.request.execution_context.broker_connection_id is None
    assert step.paper_outcome is not None
    assert step.paper_outcome.fill is not None
    assert step.paper_outcome.fill.quantity == Decimal("2")
    assert step.note == "paper executed"
    assert accounting.applications == [step.paper_outcome.fill]



def test_flow_paper_rehearsal_rejects_deployment_identity_or_version_mismatch() -> None:
    plan = _flow_plan()
    mismatched_id = replace(_deployment(), strategy_id="different-strategy")
    with pytest.raises(ValueError, match="strategy id"):
        _rehearsal_session(plan, deployment=mismatched_id)

    mismatched_version = replace(_deployment(), strategy_version="2")
    with pytest.raises(ValueError, match="strategy version"):
        _rehearsal_session(plan, deployment=mismatched_version)


def test_flow_paper_rehearsal_venue_mismatch_blocks_before_preparation() -> None:
    foreign_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    deployment = replace(_deployment(), market=foreign_market)
    session, accounting = _rehearsal_session(_flow_plan(), deployment=deployment)

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    step = result.steps[0]
    assert step.evaluation is None
    assert step.preparation is None
    assert step.paper_outcome is None
    assert step.faults
    assert "venue" in step.faults[0].message
    assert accounting.applications == []


def test_flow_paper_rehearsal_missing_instrument_metadata_blocks_preparation() -> None:
    session, accounting = _rehearsal_session(
        _flow_plan(),
        instrument_registry=InMemoryInstrumentRegistry(()),
    )

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    step = result.steps[0]
    assert step.evaluation is not None
    assert step.preparation is None
    assert step.paper_outcome is None
    assert step.faults
    assert "instrument metadata unavailable" in step.faults[0].message
    assert accounting.applications == []


def test_flow_paper_rehearsal_risk_rejection_never_reaches_paper_executor() -> None:
    plan = _flow_plan(quantity="2000")
    session, accounting = _rehearsal_session(plan)

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    step = result.steps[0]
    assert step.evaluation is not None
    assert step.preparation is not None
    assert step.preparation.risk_result is not None
    assert step.preparation.risk_result.decision is RiskDecision.REJECT
    assert step.preparation.policy_result is None
    assert step.preparation.request is None
    assert step.paper_outcome is None
    assert accounting.applications == []


class _RejectingPolicyEngine(ExecutionPolicyEngine):
    def evaluate(self, intent: TradeIntent, context: PolicyContext) -> PolicyResult:
        return PolicyResult(PolicyDecision.REJECT, "integration test policy rejection")


def test_flow_paper_rehearsal_policy_rejection_never_reaches_paper_executor() -> None:
    session, accounting = _rehearsal_session(
        _flow_plan(),
        policy_engine=_RejectingPolicyEngine(),
    )

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    step = result.steps[0]
    assert step.preparation is not None
    assert step.preparation.risk_result is not None
    assert step.preparation.risk_result.decision is RiskDecision.APPROVE
    assert step.preparation.policy_result is not None
    assert step.preparation.policy_result.decision is PolicyDecision.REJECT
    assert step.preparation.request is None
    assert step.paper_outcome is None
    assert accounting.applications == []


def test_flow_paper_hold_without_intent_has_no_preparation_or_paper_effect() -> None:
    session, accounting = _rehearsal_session(
        _flow_plan(action="HOLD", side=None),
    )

    result = session.run((RehearsalInput(_event(), _market_snapshot()),))

    step = result.steps[0]
    assert step.evaluation is not None
    assert step.evaluation.result.signal.action is SignalAction.HOLD
    assert step.evaluation.result.intent is None
    assert step.preparation is not None
    assert step.preparation.request is None
    assert step.paper_outcome is None
    assert accounting.applications == []


def test_flow_backtest_uses_strategy_evaluation_and_canonical_offline_consumers() -> None:
    result = _backtest(_flow_plan())

    assert result.executed_count == 1
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.disposition is BacktestDisposition.EXECUTED
    assert step.strategy_result is not None
    assert step.strategy_result.signal.action is SignalAction.BUY
    assert step.strategy_result.signal.strategy_id == _STRATEGY_ID
    assert step.strategy_result.signal.strategy_version == _VERSION
    assert step.strategy_result.signal.instrument == _instrument().instrument_id
    assert step.strategy_result.signal.generated_at == _NOW
    assert step.strategy_result.intent is not None
    assert step.strategy_result.intent.quantity == Decimal("2")
    assert step.risk_result is not None
    assert step.risk_result.decision is RiskDecision.APPROVE
    assert step.policy_result is not None
    assert step.policy_result.approved
    assert step.receipt is not None
    assert len(result.receipts) == 1
    assert result.receipts[0].fills
    assert result.receipts[0].fills[0].quantity == Decimal("2")
    assert result.ledger
    assert result.ledger[0].quantity == Decimal("2")
    assert result.fidelity.deterministic
    assert result.fidelity.simulated


def test_flow_backtest_repeat_runs_preserve_semantics_and_flow_identifiers() -> None:
    plan = _flow_plan()
    first = _backtest(plan)
    second = _backtest(plan)

    first_step, second_step = first.steps[0], second.steps[0]
    assert first_step.strategy_result is not None
    assert second_step.strategy_result is not None
    assert (
        first_step.strategy_result.signal.signal_id
        == second_step.strategy_result.signal.signal_id
    )
    assert first_step.strategy_result.intent is not None
    assert second_step.strategy_result.intent is not None
    assert (
        first_step.strategy_result.intent.intent_id
        == second_step.strategy_result.intent.intent_id
    )
    assert first_step.disposition is second_step.disposition
    assert first_step.risk_result == second_step.risk_result
    assert first_step.policy_result == second_step.policy_result
    assert first.receipts[0].fills[0].quantity == second.receipts[0].fills[0].quantity
    assert first.receipts[0].fills[0].price == second.receipts[0].fills[0].price
    assert first.ledger[0].quantity == second.ledger[0].quantity


class _PythonEquivalentStrategy:
    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        event = context.event
        assert event is not None
        return StrategyResult(
            signal=StrategySignal(
                strategy_id=context.ir.strategy_id,
                strategy_version=context.ir.version,
                instrument=event.instrument,
                action=SignalAction.BUY,
                confidence=0.75,
                generated_at=event.timestamp,
                reason="offline Flow decision",
            ),
            intent=TradeIntent(
                instrument=event.instrument,
                side=OrderSide.BUY,
                quantity=Decimal("2"),
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
            ),
        )


def test_flow_and_python_strategies_have_same_backtest_semantics() -> None:
    flow = _backtest(_flow_plan())
    python = _backtest(_flow_plan(), strategy=_PythonEquivalentStrategy())

    flow_step, python_step = flow.steps[0], python.steps[0]
    assert flow_step.strategy_result is not None
    assert python_step.strategy_result is not None
    assert flow_step.strategy_result.signal.action is python_step.strategy_result.signal.action
    assert flow_step.strategy_result.signal.confidence == python_step.strategy_result.signal.confidence
    assert flow_step.strategy_result.signal.reason == python_step.strategy_result.signal.reason
    assert flow_step.strategy_result.signal.generated_at == python_step.strategy_result.signal.generated_at
    assert flow_step.strategy_result.signal.instrument == python_step.strategy_result.signal.instrument
    assert flow_step.strategy_result.intent is not None
    assert python_step.strategy_result.intent is not None
    assert flow_step.strategy_result.intent.side is python_step.strategy_result.intent.side
    assert flow_step.strategy_result.intent.quantity == python_step.strategy_result.intent.quantity
    assert flow_step.risk_result is not None and python_step.risk_result is not None
    assert flow_step.risk_result.decision is python_step.risk_result.decision
    assert flow_step.policy_result is not None and python_step.policy_result is not None
    assert flow_step.policy_result.decision is python_step.policy_result.decision
    assert flow_step.receipt is not None and python_step.receipt is not None
    assert flow_step.receipt.fills[0].quantity == python_step.receipt.fills[0].quantity
    assert flow_step.receipt.fills[0].price == python_step.receipt.fills[0].price
    assert flow.ledger[0].quantity == python.ledger[0].quantity
