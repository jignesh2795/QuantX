"""Contract tests for Flow's existing ExecutableStrategy integration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderSide
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    EngineStateSnapshot,
    EvidenceAvailability,
    EvidenceCollection,
)
from quantx.strategy.flow import (
    FlowCompiler,
    FlowDefinition,
    FlowEdge,
    FlowEvaluationError,
    FlowExecutableStrategy,
    FlowExecutionPlan,
    FlowInterpreter,
    FlowNode,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry
from quantx.strategy.runtime import ExecutableStrategy, StrategyRuntime

_NOW = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
_INSTRUMENT = InstrumentId("NSE", "FLOWTEST")
_STRATEGY_ID = StrategyId("flow-runtime-adapter-test")


def _event() -> MarketDataEvent:
    return MarketDataEvent(
        data_type=MarketDataType.QUOTE,
        timestamp=_NOW,
        instrument=_INSTRUMENT,
        payload=Quote(
            instrument=_INSTRUMENT,
            timestamp=_NOW,
            bid=Decimal("99"),
            ask=Decimal("101"),
            last=Decimal("100"),
        ),
    )


def _ir() -> StrategyIR:
    return StrategyIR(
        strategy_id=_STRATEGY_ID,
        version="1",
        name="Flow runtime adapter test",
        market_contexts=(),
        parameters=(),
    )


def _engine(as_of: datetime = _NOW) -> EngineStateSnapshot:
    return EngineStateSnapshot(
        as_of=as_of,
        positions=EvidenceCollection.known(()),
        orders=EvidenceCollection.known(()),
        account_state=None,
        account_availability=EvidenceAvailability.UNAVAILABLE,
        account_reason="account facts are outside this Flow adapter test",
    )


def _history_candle() -> Candle:
    timestamp = _NOW - timedelta(minutes=1)
    return Candle(
        instrument=_INSTRUMENT,
        timeframe="1m",
        timestamp=timestamp,
        open=Decimal("98"),
        high=Decimal("101"),
        low=Decimal("97"),
        close=Decimal("100"),
        volume=Decimal("10"),
    )


def _context(*, history: tuple[Candle, ...] = ()) -> StrategyContext:
    return StrategyContext(
        event=_event(),
        ir=_ir(),
        as_of=_NOW,
        engine=_engine(),
        history=history,
    )


def _definition(
    *,
    strategy_id: StrategyId = _STRATEGY_ID,
    version: str = "1",
    action: str = "BUY",
    intent_side: str | None = None,
) -> FlowDefinition:
    nodes = [
        FlowNode("action", "signal_action_constant", (("value", action),)),
        FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        FlowNode("reason", "string_constant", (("value", "flow decision"),)),
        FlowNode("result", "strategy_result"),
    ]
    edges = [
        FlowEdge("result-action", "action", "value", "result", "action"),
        FlowEdge("result-confidence", "confidence", "value", "result", "confidence"),
        FlowEdge("result-reason", "reason", "value", "result", "reason"),
    ]
    if intent_side is not None:
        nodes.extend(
            (
                FlowNode(
                    "intent",
                    "trade_intent",
                    (
                        ("order_type", "MARKET"),
                        ("side", intent_side),
                        ("time_in_force", "DAY"),
                    ),
                ),
                FlowNode("quantity", "decimal_constant", (("value", "2"),)),
            )
        )
        edges.extend(
            (
                FlowEdge("quantity-intent", "quantity", "value", "intent", "quantity"),
                FlowEdge("result-intent", "intent", "intent", "result", "intent"),
            )
        )
    return FlowDefinition(
        strategy_id=strategy_id,
        version=version,
        name="Flow runtime adapter test",
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def _plan(
    *,
    strategy_id: StrategyId = _STRATEGY_ID,
    version: str = "1",
    action: str = "BUY",
    intent_side: str | None = None,
) -> FlowExecutionPlan:
    return FlowCompiler().compile(
        _definition(
            strategy_id=strategy_id,
            version=version,
            action=action,
            intent_side=intent_side,
        )
    )


def test_adapter_satisfies_executable_strategy_and_uses_existing_runtime() -> None:
    plan = _plan()
    strategy: ExecutableStrategy = FlowExecutableStrategy(plan)

    result = StrategyRuntime(strategy).evaluate(_event(), _ir(), engine=_engine())

    assert isinstance(result, StrategyResult)
    assert result.signal.action is SignalAction.BUY
    assert result.signal.strategy_id == _STRATEGY_ID
    assert result.signal.strategy_version == "1"
    assert result.signal.instrument == _INSTRUMENT
    assert result.signal.generated_at == _NOW
    assert result.intent is None
    assert _ir().parameters == ()


def test_adapter_passes_the_exact_context_and_plan_to_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    history = (_history_candle(),)
    context = _context(history=history)
    captured: list[tuple[FlowExecutionPlan, StrategyContext]] = []
    original = FlowInterpreter.evaluate

    def capture(
        interpreter: FlowInterpreter,
        supplied_plan: FlowExecutionPlan,
        supplied_context: StrategyContext,
    ) -> StrategyResult:
        captured.append((supplied_plan, supplied_context))
        return original(interpreter, supplied_plan, supplied_context)

    monkeypatch.setattr(FlowInterpreter, "evaluate", capture)

    result = FlowExecutableStrategy(plan).on_market_data(context)

    assert isinstance(result, StrategyResult)
    assert len(captured) == 1
    assert captured[0][0] is plan
    assert captured[0][1] is context
    assert captured[0][1].event is context.event
    assert captured[0][1].ir is context.ir
    assert captured[0][1].as_of == context.as_of
    assert captured[0][1].engine is context.engine
    assert captured[0][1].history is context.history


def test_adapter_propagates_interpreter_exception_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = FlowEvaluationError("sentinel_failure", "sentinel failure")

    def fail(
        interpreter: FlowInterpreter,
        plan: FlowExecutionPlan,
        context: StrategyContext,
    ) -> StrategyResult:
        raise error

    monkeypatch.setattr(FlowInterpreter, "evaluate", fail)

    with pytest.raises(FlowEvaluationError) as caught:
        FlowExecutableStrategy(_plan()).on_market_data(_context())

    assert caught.value is error


def test_adapter_rejects_non_plan_input_at_construction() -> None:
    with pytest.raises(TypeError, match="FlowExecutionPlan"):
        FlowExecutableStrategy(object())  # type: ignore[arg-type]


def test_interpreter_revalidation_rejects_fabricated_plan_through_adapter() -> None:
    valid_plan = _plan()
    fabricated = replace(valid_plan, fingerprint=f"sha256:{'0' * 64}")

    with pytest.raises(FlowEvaluationError, match="invalid_execution_plan"):
        StrategyRuntime(FlowExecutableStrategy(fabricated)).evaluate(
            _event(),
            _ir(),
            engine=_engine(),
        )


@pytest.mark.parametrize(
    ("plan", "diagnostic"),
    [
        (_plan(strategy_id=StrategyId("different-flow")), "strategy_identity_mismatch"),
        (_plan(version="2"), "strategy_version_mismatch"),
    ],
)
def test_flow_identity_must_match_runtime_ir(
    plan: FlowExecutionPlan,
    diagnostic: str,
) -> None:
    with pytest.raises(FlowEvaluationError, match=diagnostic):
        StrategyRuntime(FlowExecutableStrategy(plan)).evaluate(
            _event(),
            _ir(),
            engine=_engine(),
        )


@pytest.mark.parametrize(
    ("action", "intent_side", "message"),
    [
        ("BUY", "SELL", "BUY signal must carry a BUY intent"),
        ("SELL", "BUY", "SELL signal must carry a SELL intent"),
    ],
)
def test_existing_runtime_remains_authoritative_for_intent_direction(
    action: str,
    intent_side: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        StrategyRuntime(
            FlowExecutableStrategy(_plan(action=action, intent_side=intent_side))
        ).evaluate(_event(), _ir(), engine=_engine())


@pytest.mark.parametrize(
    ("action", "intent_side"),
    [
        ("BUY", "BUY"),
        ("SELL", "SELL"),
    ],
)
def test_matching_flow_action_and_intent_are_accepted(
    action: str,
    intent_side: str,
) -> None:
    result = StrategyRuntime(
        FlowExecutableStrategy(_plan(action=action, intent_side=intent_side))
    ).evaluate(_event(), _ir(), engine=_engine())

    assert result.intent is not None
    assert result.intent.side is (OrderSide.BUY if action == "BUY" else OrderSide.SELL)
    assert result.intent.quantity == Decimal("2")
    assert result.intent.strategy_id == _STRATEGY_ID.value
    assert result.intent.strategy_version == "1"


def test_existing_registry_constructs_fresh_flow_strategy_instances() -> None:
    plan = _plan()
    registry = StrategyRegistry()
    registry.register(
        _STRATEGY_ID.value,
        "1",
        lambda: FlowExecutableStrategy(plan),
    )

    first = registry.resolve(_ir())
    second = registry.resolve(_ir())

    assert isinstance(first, FlowExecutableStrategy)
    assert isinstance(second, FlowExecutableStrategy)
    assert first is not second
    result = StrategyRuntime(first).evaluate(_event(), _ir(), engine=_engine())
    assert result.signal.action is SignalAction.BUY


def test_flow_and_python_strategies_share_semantic_result_contract() -> None:
    class PythonEquivalentStrategy:
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
                    reason="flow decision",
                ),
                intent=TradeIntent(
                    instrument=event.instrument,
                    side=OrderSide.BUY,
                    quantity=Decimal("2"),
                    strategy_id=context.ir.strategy_id.value,
                    strategy_version=context.ir.version,
                ),
            )

    flow_strategy = FlowExecutableStrategy(_plan(intent_side="BUY"))
    flow_result = StrategyRuntime(flow_strategy).evaluate(_event(), _ir(), engine=_engine())
    python_result = StrategyRuntime(PythonEquivalentStrategy()).evaluate(
        _event(),
        _ir(),
        engine=_engine(),
    )

    assert flow_result.signal.action is python_result.signal.action
    assert flow_result.signal.confidence == python_result.signal.confidence
    assert flow_result.signal.reason == python_result.signal.reason
    assert flow_result.signal.generated_at == python_result.signal.generated_at
    assert flow_result.signal.instrument == python_result.signal.instrument
    assert flow_result.signal.strategy_id == python_result.signal.strategy_id
    assert flow_result.signal.strategy_version == python_result.signal.strategy_version
    assert flow_result.intent is not None
    assert python_result.intent is not None
    assert flow_result.intent.side is python_result.intent.side
    assert flow_result.intent.quantity == python_result.intent.quantity
    assert flow_result.intent.order_type is python_result.intent.order_type
    assert flow_result.intent.time_in_force is python_result.intent.time_in_force
    assert flow_result.intent.strategy_id == python_result.intent.strategy_id
    assert flow_result.intent.strategy_version == python_result.intent.strategy_version


def test_repeated_adapter_evaluations_keep_flow_identifiers_deterministic() -> None:
    plan = _plan(intent_side="BUY")
    strategy = FlowExecutableStrategy(plan)

    first = StrategyRuntime(strategy).evaluate(_event(), _ir(), engine=_engine())
    second = StrategyRuntime(strategy).evaluate(_event(), _ir(), engine=_engine())

    assert first.signal.signal_id == second.signal.signal_id
    assert first.intent is not None and second.intent is not None
    assert first.intent.intent_id == second.intent.intent_id
