"""Behavioral, determinism and capability-boundary tests for Flow v1 compilation/evaluation."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult
from quantx.domain.value_objects import InstrumentId
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    EngineStateSnapshot,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
)
from quantx.strategy.flow import (
    FLOW_DECIMAL_CONTRACT_VERSION,
    FLOW_DECIMAL_EMAX,
    FLOW_DECIMAL_EMIN,
    FLOW_DECIMAL_PRECISION,
    FLOW_DECIMAL_ROUNDING,
    FlowCompiler,
    FlowDefinition,
    FlowDefinitionValidationError,
    FlowEdge,
    FlowEvaluationError,
    FlowExecutionPlan,
    FlowInputBinding,
    FlowInstruction,
    FlowInterpreter,
    FlowNode,
)
from quantx.strategy.ir import StrategyIR

_NOW = datetime(2026, 11, 7, 9, 30, tzinfo=UTC)
_INSTRUMENT = InstrumentId("NSE", "FLOWTEST")
_OTHER_INSTRUMENT = InstrumentId("NSE", "OTHER")
_STRATEGY_ID = StrategyId("flow-test")


def _ir() -> StrategyIR:
    return StrategyIR(
        strategy_id=_STRATEGY_ID,
        version="1",
        name="Flow test",
        market_contexts=(),
        parameters=(),
    )


def _event(
    payload: Quote | Candle | None = None,
    *,
    data_type: MarketDataType | str | None = None,
    timestamp: datetime = _NOW,
) -> MarketDataEvent:
    if payload is None:
        payload = Quote(
            instrument=_INSTRUMENT,
            timestamp=timestamp,
            bid=Decimal("99"),
            ask=Decimal("101"),
            last=Decimal("100"),
        )
    if data_type is None:
        data_type = MarketDataType.QUOTE if isinstance(payload, Quote) else MarketDataType.CANDLE
    return MarketDataEvent(
        data_type=data_type,  # type: ignore[arg-type]
        timestamp=timestamp,
        instrument=_INSTRUMENT,
        payload=payload,
    )


def _snapshot(
    *,
    as_of: datetime = _NOW,
    positions: EvidenceCollection[PositionFact] | None = None,
    orders: EvidenceCollection[OpenOrderFact] | None = None,
) -> EngineStateSnapshot:
    return EngineStateSnapshot(
        as_of=as_of,
        positions=positions if positions is not None else EvidenceCollection.known(()),
        orders=orders if orders is not None else EvidenceCollection.known(()),
        account_state=None,
        account_availability=EvidenceAvailability.UNAVAILABLE,
        account_reason="account facts are outside the Flow v1 input catalogue",
    )


def _context(
    *,
    event: MarketDataEvent | None = None,
    as_of: datetime | None = None,
    history: tuple[Candle, ...] = (),
    positions: EvidenceCollection[PositionFact] | None = None,
    orders: EvidenceCollection[OpenOrderFact] | None = None,
) -> StrategyContext:
    selected_event = _event() if event is None else event
    logical_time = as_of if as_of is not None else selected_event.timestamp
    return StrategyContext(
        event=selected_event,
        ir=_ir(),
        as_of=logical_time,
        engine=_snapshot(as_of=logical_time, positions=positions, orders=orders),
        history=history,
    )


def _flow(
    *,
    extra_nodes: tuple[FlowNode, ...] = (),
    extra_edges: tuple[FlowEdge, ...] = (),
    action_source: str = "action",
    confidence_source: str = "confidence",
    reason_source: str = "reason",
    intent_source: str | None = None,
    action_value: str = "BUY",
    confidence_value: str = "0.75",
    reason_value: str = "flow decision",
) -> FlowDefinition:
    nodes = list(extra_nodes)
    if action_source == "action":
        nodes.append(FlowNode("action", "signal_action_constant", (("value", action_value),)))
    if confidence_source == "confidence":
        nodes.append(FlowNode("confidence", "confidence_constant", (("value", confidence_value),)))
    if reason_source == "reason":
        nodes.append(FlowNode("reason", "string_constant", (("value", reason_value),)))
    nodes.append(FlowNode("result", "strategy_result"))
    edges = list(extra_edges)
    edges.extend(
        (
            FlowEdge("result-action", action_source, "value", "result", "action"),
            FlowEdge("result-confidence", confidence_source, "value", "result", "confidence"),
            FlowEdge("result-reason", reason_source, "value", "result", "reason"),
        )
    )
    if intent_source is not None:
        edges.append(FlowEdge("result-intent", intent_source, "intent", "result", "intent"))
    return FlowDefinition(
        strategy_id=_STRATEGY_ID,
        version="1",
        name="Flow test",
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def _intent_node(*, side: str = "BUY") -> FlowNode:
    return FlowNode(
        "intent",
        "trade_intent",
        (("order_type", "MARKET"), ("side", side), ("time_in_force", "DAY")),
    )


def _evaluate(
    definition: FlowDefinition,
    context: StrategyContext | None = None,
) -> StrategyResult:
    plan = FlowCompiler().compile(definition)
    return FlowInterpreter().evaluate(plan, _context() if context is None else context)


def _position(
    quantity: Decimal,
    *,
    instrument: InstrumentId = _INSTRUMENT,
    at: datetime = _NOW,
) -> PositionFact:
    return PositionFact(
        instrument=instrument,
        quantity=quantity,
        average_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
        effective_at=at,
        evidence_time=at,
    )


def _order(
    status: OrderStatus,
    *,
    instrument: InstrumentId = _INSTRUMENT,
    client_order_id: str = "order-1",
) -> OpenOrderFact:
    filled = Decimal("10") if status is OrderStatus.FILLED else None
    remaining = Decimal("0") if status is OrderStatus.FILLED else None
    return OpenOrderFact(
        client_order_id=client_order_id,
        instrument=instrument,
        status=status,
        order_quantity=Decimal("10"),
        filled_quantity=filled,
        remaining_quantity=remaining,
        created_at=_NOW,
        evidence_time=_NOW,
        effective_at=_NOW,
    )


def test_compiler_produces_a_stable_immutable_topological_plan() -> None:
    definition = _flow()
    reordered = replace(
        definition,
        nodes=tuple(reversed(definition.nodes)),
        edges=tuple(reversed(definition.edges)),
    )

    first = FlowCompiler().compile(definition)
    second = FlowCompiler().compile(reordered)

    assert first == second
    assert first.fingerprint.startswith("sha256:")
    assert first.plan_id == second.plan_id
    assert tuple(item.node.node_id for item in first.instructions) == (
        "action",
        "confidence",
        "reason",
        "result",
    )
    assert isinstance(first.instructions, tuple)
    with pytest.raises(FrozenInstanceError):
        first.fingerprint = "changed"  # type: ignore[misc]


def test_compiler_plan_and_bindings_reject_mutable_inputs() -> None:
    node = FlowNode("constant", "decimal_constant", (("value", "1"),))
    with pytest.raises(TypeError, match="immutable tuple"):
        FlowInstruction(node=node, inputs=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="immutable tuple"):
        FlowExecutionPlan(
            definition=_flow(),
            instructions=[],
            fingerprint="sha256:x",
        )  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="FlowNode"):
        FlowInstruction(node="not-a-node", inputs=())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique sorted ports"):
        FlowInstruction(
            node=node,
            inputs=(
                FlowInputBinding("value", "a", "value"),
                FlowInputBinding("value", "b", "value"),
            ),
        )


def test_compiler_rejects_invalid_graph_before_any_evaluation() -> None:
    definition = _flow()
    invalid = replace(
        definition,
        edges=tuple(edge for edge in definition.edges if edge.edge_id != "result-action"),
    )

    with pytest.raises(FlowDefinitionValidationError):
        FlowCompiler().compile(invalid)


def test_interpreter_recompiles_and_rejects_a_fabricated_plan() -> None:
    plan = FlowCompiler().compile(_flow())
    fabricated = replace(plan, fingerprint=f"sha256:{'0' * 64}")

    with pytest.raises(FlowEvaluationError, match="invalid_execution_plan"):
        FlowInterpreter().evaluate(fabricated, _context())


def test_result_uses_existing_domain_types_and_event_time() -> None:
    result = _evaluate(_flow())

    assert isinstance(result, StrategyResult)
    assert result.signal.strategy_id == _STRATEGY_ID
    assert result.signal.strategy_version == "1"
    assert result.signal.instrument == _INSTRUMENT
    assert result.signal.action is SignalAction.BUY
    assert result.signal.confidence == 0.75
    assert result.signal.reason == "flow decision"
    assert result.signal.generated_at == _NOW
    assert result.intent is None


def test_repeated_identical_invocations_have_stable_signal_and_intent_ids() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("quantity", "decimal_constant", (("value", "2"),)),
            _intent_node(),
        ),
        extra_edges=(FlowEdge("quantity-intent", "quantity", "value", "intent", "quantity"),),
        intent_source="intent",
    )
    first = _evaluate(definition)
    second = _evaluate(definition)

    assert first.signal.signal_id == second.signal.signal_id
    assert first.intent is not None and second.intent is not None
    assert first.intent.intent_id == second.intent.intent_id
    assert first == second


def test_trade_intent_is_a_passive_domain_value_with_explicit_constraints() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("quantity", "decimal_constant", (("value", "2.5"),)),
            _intent_node(side="SELL"),
        ),
        extra_edges=(FlowEdge("quantity-intent", "quantity", "value", "intent", "quantity"),),
        intent_source="intent",
        action_value="SELL",
    )

    result = _evaluate(definition)

    assert result.intent is not None
    assert result.intent.instrument == _INSTRUMENT
    assert result.intent.side.value == "SELL"
    assert result.intent.quantity == Decimal("2.5")
    assert result.intent.order_type.value == "MARKET"
    assert result.intent.time_in_force.value == "DAY"
    assert result.intent.strategy_id == _STRATEGY_ID.value
    assert result.intent.strategy_version == "1"
    assert result.intent.execution_context is None
    assert result.intent.approval_required is False


@pytest.mark.parametrize(
    ("operator", "left", "right", "expected"),
    [
        ("ADD", "2", "3", Decimal("5")),
        ("SUBTRACT", "5", "2", Decimal("3")),
        ("MULTIPLY", "5", "2", Decimal("10")),
        ("DIVIDE", "10", "2", Decimal("5")),
    ],
)
def test_decimal_binary_operators(operator: str, left: str, right: str, expected: Decimal) -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("left", "decimal_constant", (("value", left),)),
            FlowNode("right", "decimal_constant", (("value", right),)),
            FlowNode("calculation", "decimal_binary", (("operator", operator),)),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("left-calc", "left", "value", "calculation", "left"),
            FlowEdge("right-calc", "right", "value", "calculation", "right"),
            FlowEdge("calc-intent", "calculation", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition)

    assert result.intent is not None
    assert result.intent.quantity == expected


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("EQ", False),
        ("GT", True),
        ("GTE", True),
        ("LT", False),
        ("LTE", False),
        ("NE", True),
    ],
)
def test_decimal_comparison_operators(operator: str, expected: bool) -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("left", "decimal_constant", (("value", "5"),)),
            FlowNode("right", "decimal_constant", (("value", "2"),)),
            FlowNode("comparison", "decimal_compare", (("operator", operator),)),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("left-compare", "left", "value", "comparison", "left"),
            FlowEdge("right-compare", "right", "value", "comparison", "right"),
            FlowEdge("condition-select", "comparison", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    result = _evaluate(definition)

    assert result.signal.action is (SignalAction.BUY if expected else SignalAction.SELL)


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("AND", False), ("OR", True)],
)
def test_boolean_binary_operators(operator: str, expected: bool) -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("left", "boolean_constant", (("value", "true"),)),
            FlowNode("right", "boolean_constant", (("value", "false"),)),
            FlowNode("combine", "boolean_binary", (("operator", operator),)),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("left-combine", "left", "value", "combine", "left"),
            FlowEdge("right-combine", "right", "value", "combine", "right"),
            FlowEdge("condition-select", "combine", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    result = _evaluate(definition)

    assert result.signal.action is (SignalAction.BUY if expected else SignalAction.SELL)


def test_boolean_not_node() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("source", "boolean_constant", (("value", "true"),)),
            FlowNode("not", "boolean_not"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("source-not", "source", "value", "not", "value"),
            FlowEdge("condition-select", "not", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    assert _evaluate(definition).signal.action is SignalAction.SELL


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("quote.ask", Decimal("101")),
        ("quote.bid", Decimal("99")),
        ("quote.last", Decimal("100")),
        ("quote.mid", Decimal("100")),
    ],
)
def test_quote_event_fields(field: str, expected: Decimal) -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("field", "event_field", (("field", field),)),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("field-required", "field", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition)

    assert result.intent is not None
    assert result.intent.quantity == expected


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("open", Decimal("10")),
        ("high", Decimal("12")),
        ("low", Decimal("9")),
        ("close", Decimal("11")),
        ("volume", Decimal("50")),
    ],
)
def test_candle_event_fields(field: str, expected: Decimal) -> None:
    candle = Candle(
        instrument=_INSTRUMENT,
        timeframe="1m",
        timestamp=_NOW,
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("50"),
    )
    definition = _flow(
        extra_nodes=(
            FlowNode("field", "event_field", (("field", f"candle.{field}"),)),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("field-required", "field", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition, _context(event=_event(candle)))

    assert result.intent is not None
    assert result.intent.quantity == expected


def test_event_field_for_other_payload_family_is_unavailable_not_coerced() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("field", "event_field", (("field", "quote.ask"),)),
            FlowNode("available", "is_available_decimal"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("field-available", "field", "value", "available", "value"),
            FlowEdge("condition-select", "available", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )
    candle = Candle(
        instrument=_INSTRUMENT,
        timeframe="1m",
        timestamp=_NOW,
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("50"),
    )

    assert _evaluate(definition, _context(event=_event(candle))).signal.action is SignalAction.SELL


def test_market_data_type_and_payload_must_match() -> None:
    event = _event(data_type=MarketDataType.CANDLE)

    with pytest.raises(FlowEvaluationError, match="event_payload_type_mismatch"):
        _evaluate(_flow(), _context(event=event))


def test_market_event_and_payload_timestamps_must_match() -> None:
    quote = Quote(
        instrument=_INSTRUMENT,
        timestamp=_NOW - timedelta(seconds=1),
        bid=Decimal("99"),
        ask=Decimal("101"),
    )
    event = _event(quote)

    with pytest.raises(FlowEvaluationError, match="event_payload_timestamp_mismatch"):
        _evaluate(_flow(), _context(event=event))


def test_quote_midpoint_uses_the_pinned_decimal_context() -> None:
    event = _event(
        Quote(
            instrument=_INSTRUMENT,
            timestamp=_NOW,
            bid=Decimal("1.000000000000000000000000000000000"),
            ask=Decimal("1.000000000000000000000000000000001"),
        )
    )
    definition = _flow(
        extra_nodes=(
            FlowNode("mid", "event_field", (("field", "quote.mid"),)),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("mid-required", "mid", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    with localcontext() as ambient:
        ambient.prec = 2
        result = _evaluate(definition, _context(event=event))

    assert result.intent is not None
    assert result.intent.quantity == Decimal("1.000000000000000000000000000000000")


def test_prior_candle_bars_ago_one_is_the_latest_strictly_prior_candle() -> None:
    first = Candle(
        instrument=_INSTRUMENT,
        timeframe="1m",
        timestamp=_NOW - timedelta(minutes=2),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("1"),
    )
    latest = replace(first, timestamp=_NOW - timedelta(minutes=1), close=Decimal("12"))
    definition = _flow(
        extra_nodes=(
            FlowNode("prior", "prior_candle_field", (("bars_ago", "1"), ("field", "close"))),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("prior-required", "prior", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition, _context(history=(first, latest)))

    assert result.intent is not None
    assert result.intent.quantity == Decimal("12")


def test_prior_candle_bars_ago_two_selects_the_second_latest_candle() -> None:
    first = Candle(
        instrument=_INSTRUMENT,
        timeframe="1m",
        timestamp=_NOW - timedelta(minutes=2),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("1"),
    )
    latest = replace(first, timestamp=_NOW - timedelta(minutes=1), close=Decimal("12"))
    definition = _flow(
        extra_nodes=(
            FlowNode("prior", "prior_candle_field", (("bars_ago", "2"), ("field", "close"))),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("prior-required", "prior", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition, _context(history=(first, latest)))

    assert result.intent is not None
    assert result.intent.quantity == Decimal("11")


def test_prior_history_insufficiency_remains_unavailable() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("prior", "prior_candle_field", (("bars_ago", "1"), ("field", "close"))),
            FlowNode("available", "is_available_decimal"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("prior-available", "prior", "value", "available", "value"),
            FlowEdge("condition-select", "available", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    assert _evaluate(definition).signal.action is SignalAction.SELL


@pytest.mark.parametrize(
    ("history", "code", "as_of"),
    [
        (
            (
                Candle(
                    _INSTRUMENT,
                    "1m",
                    _NOW - timedelta(minutes=1),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("1"),
                ),
                Candle(
                    _INSTRUMENT,
                    "1m",
                    _NOW - timedelta(minutes=2),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("1"),
                ),
            ),
            "history_not_chronological",
            _NOW,
        ),
        (
            (
                Candle(
                    _INSTRUMENT,
                    "1m",
                    _NOW - timedelta(minutes=1),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("1"),
                ),
                Candle(
                    _INSTRUMENT,
                    "1m",
                    _NOW - timedelta(minutes=1),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("1"),
                ),
            ),
            "duplicate_history_timestamp",
            _NOW,
        ),
        (
            (
                Candle(
                    _INSTRUMENT,
                    "1m",
                    _NOW + timedelta(minutes=1),
                    Decimal("1"),
                    Decimal("2"),
                    Decimal("1"),
                    Decimal("1"),
                ),
            ),
            "history_lookahead",
            _NOW + timedelta(minutes=2),
        ),
    ],
)
def test_history_order_uniqueness_and_event_cut_are_fail_closed(
    history: tuple[Candle, ...],
    code: str,
    as_of: datetime,
) -> None:
    context = _context(as_of=as_of, history=history)

    with pytest.raises(FlowEvaluationError) as caught:
        _evaluate(_flow(), context)

    assert caught.value.code == code


def test_context_history_is_bounded_to_flow_v1_limit() -> None:
    # StrategyContext deliberately validates type/time/instrument but leaves
    # Flow's stricter execution bound to this interpreter boundary.
    candles = tuple(
        Candle(
            instrument=_INSTRUMENT,
            timeframe="1m",
            timestamp=_NOW - timedelta(minutes=600 - index),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("1"),
            close=Decimal("1"),
        )
        for index in range(513)
    )
    context = _context(history=candles)

    with pytest.raises(FlowEvaluationError, match="history_limit_exceeded"):
        _evaluate(_flow(), context)


def test_require_decimal_rejects_unavailable_event_value() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("field", "event_field", (("field", "quote.ask"),)),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("field-required", "field", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )
    context = _context(event=_event(Quote(_INSTRUMENT, _NOW, bid=Decimal("1"))))

    with pytest.raises(FlowEvaluationError) as caught:
        _evaluate(definition, context)

    assert caught.value.code == "required_decimal_unavailable"
    assert caught.value.node_id == "required"


def test_require_boolean_rejects_unavailable_order_evidence() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("orders", "engine_active_order_exists"),
            FlowNode("required", "require_boolean"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("orders-required", "orders", "value", "required", "value"),
            FlowEdge("condition-select", "required", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )
    context = _context(orders=EvidenceCollection.unavailable("order snapshot not supplied"))

    with pytest.raises(FlowEvaluationError, match="required_boolean_unavailable"):
        _evaluate(definition, context)


def test_is_available_boolean_preserves_unknown_order_collection() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("orders", "engine_active_order_exists"),
            FlowNode("available", "is_available_boolean"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("orders-available", "orders", "value", "available", "value"),
            FlowEdge("condition-select", "available", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )
    context = _context(orders=EvidenceCollection.incomplete((), "partial order inventory"))

    assert _evaluate(definition, context).signal.action is SignalAction.SELL


def test_is_available_decimal_distinguishes_missing_quote_from_available_value() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("field", "event_field", (("field", "quote.ask"),)),
            FlowNode("available", "is_available_decimal"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("field-available", "field", "value", "available", "value"),
            FlowEdge("condition-select", "available", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )
    missing = _context(event=_event(Quote(_INSTRUMENT, _NOW, bid=Decimal("99"))))

    assert _evaluate(definition, missing).signal.action is SignalAction.SELL
    assert _evaluate(definition).signal.action is SignalAction.BUY


def test_select_decimal_uses_only_the_selected_branch_value() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("condition", "boolean_constant", (("value", "false"),)),
            FlowNode("false-value", "decimal_constant", (("value", "3"),)),
            FlowNode("true-value", "decimal_constant", (("value", "9"),)),
            FlowNode("select-value", "select_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("condition-select", "condition", "value", "select-value", "condition"),
            FlowEdge("false-select", "false-value", "value", "select-value", "when_false"),
            FlowEdge("true-select", "true-value", "value", "select-value", "when_true"),
            FlowEdge("selected-intent", "select-value", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    result = _evaluate(definition)

    assert result.intent is not None
    assert result.intent.quantity == Decimal("3")


def test_engine_position_quantity_uses_authoritative_current_instrument_fact() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("position", "engine_position_quantity"),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("position-required", "position", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )
    context = _context(positions=EvidenceCollection.known((_position(Decimal("4")),)))

    result = _evaluate(definition, context)

    assert result.intent is not None
    assert result.intent.quantity == Decimal("4")


def test_known_empty_position_collection_is_zero_not_unknown() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("position", "engine_position_quantity"),
            FlowNode("required", "require_decimal"),
            FlowNode("zero", "decimal_constant", (("value", "0"),)),
            FlowNode("comparison", "decimal_compare", (("operator", "GT"),)),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("position-required", "position", "value", "required", "value"),
            FlowEdge("required-compare", "required", "value", "comparison", "left"),
            FlowEdge("zero-compare", "zero", "value", "comparison", "right"),
            FlowEdge("condition-select", "comparison", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    assert _evaluate(definition).signal.action is SignalAction.SELL


def test_incomplete_position_collection_with_a_fact_stays_unavailable() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("position", "engine_position_quantity"),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("position-required", "position", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )
    context = _context(
        positions=EvidenceCollection.incomplete(
            (_position(Decimal("4")),),
            "position ledger is partial",
        )
    )

    with pytest.raises(FlowEvaluationError, match="required_decimal_unavailable"):
        _evaluate(definition, context)


def test_duplicate_complete_position_facts_fail_closed() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("position", "engine_position_quantity"),
            FlowNode("required", "require_decimal"),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("position-required", "position", "value", "required", "value"),
            FlowEdge("required-intent", "required", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )
    context = _context(
        positions=EvidenceCollection.known((_position(Decimal("1")), _position(Decimal("2"))))
    )

    with pytest.raises(FlowEvaluationError, match="ambiguous_position_evidence"):
        _evaluate(definition, context)


def _order_action_graph() -> FlowDefinition:
    return _flow(
        extra_nodes=(
            FlowNode("orders", "engine_active_order_exists"),
            FlowNode("required", "require_boolean"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("orders-required", "orders", "value", "required", "value"),
            FlowEdge("condition-select", "required", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )


def test_engine_active_order_exists_treats_unknown_as_nonterminal() -> None:
    context = _context(orders=EvidenceCollection.known((_order(OrderStatus.UNKNOWN),)))

    assert _evaluate(_order_action_graph(), context).signal.action is SignalAction.BUY


def test_incomplete_order_collection_with_a_witnessed_active_order_proves_true() -> None:
    context = _context(
        orders=EvidenceCollection.incomplete(
            (_order(OrderStatus.SUBMITTED),),
            "order inventory is incomplete",
        )
    )

    assert _evaluate(_order_action_graph(), context).signal.action is SignalAction.BUY


def test_known_empty_orders_prove_false_but_incomplete_absence_does_not() -> None:
    available = _context(orders=EvidenceCollection.known(()))
    incomplete = _context(orders=EvidenceCollection.incomplete((), "partial order inventory"))
    optional_graph = _flow(
        extra_nodes=(
            FlowNode("orders", "engine_active_order_exists"),
            FlowNode("available", "is_available_boolean"),
            FlowNode("yes", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("no", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("select", "action_select"),
        ),
        extra_edges=(
            FlowEdge("orders-available", "orders", "value", "available", "value"),
            FlowEdge("condition-select", "available", "value", "select", "condition"),
            FlowEdge("yes-select", "yes", "value", "select", "when_true"),
            FlowEdge("no-select", "no", "value", "select", "when_false"),
        ),
        action_source="select",
    )

    assert _evaluate(_order_action_graph(), available).signal.action is SignalAction.SELL
    assert _evaluate(optional_graph, incomplete).signal.action is SignalAction.SELL


def test_active_order_lookup_is_instrument_scoped_and_ignores_terminal_orders() -> None:
    other_instrument = _order(OrderStatus.SUBMITTED, instrument=_OTHER_INSTRUMENT)
    terminal = _order(OrderStatus.FILLED)
    context = _context(orders=EvidenceCollection.known((other_instrument, terminal)))

    assert _evaluate(_order_action_graph(), context).signal.action is SignalAction.SELL


def test_decimal_context_is_independent_of_ambient_precision_and_rounding() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("one", "decimal_constant", (("value", "1"),)),
            FlowNode("three", "decimal_constant", (("value", "3"),)),
            FlowNode("divide", "decimal_binary", (("operator", "DIVIDE"),)),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("one-divide", "one", "value", "divide", "left"),
            FlowEdge("three-divide", "three", "value", "divide", "right"),
            FlowEdge("divide-intent", "divide", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        result = _evaluate(definition)

    assert result.intent is not None
    assert result.intent.quantity == Decimal("0.3333333333333333333333333333333333")
    assert FLOW_DECIMAL_PRECISION == 34
    assert FLOW_DECIMAL_ROUNDING == "ROUND_HALF_EVEN"
    assert FLOW_DECIMAL_EMIN == -6143
    assert FLOW_DECIMAL_EMAX == 6144
    assert FLOW_DECIMAL_CONTRACT_VERSION == "1"


def test_division_by_zero_has_a_stable_diagnostic() -> None:
    definition = _flow(
        extra_nodes=(
            FlowNode("one", "decimal_constant", (("value", "1"),)),
            FlowNode("zero", "decimal_constant", (("value", "0"),)),
            FlowNode("divide", "decimal_binary", (("operator", "DIVIDE"),)),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("one-divide", "one", "value", "divide", "left"),
            FlowEdge("zero-divide", "zero", "value", "divide", "right"),
            FlowEdge("divide-intent", "divide", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    with pytest.raises(FlowEvaluationError) as caught:
        _evaluate(definition)

    assert caught.value.code == "division_by_zero"
    assert caught.value.node_id == "divide"


@pytest.mark.parametrize(
    ("event_value", "operator", "right", "code"),
    [
        (Decimal("1E+6144"), "MULTIPLY", "10", "decimal_arithmetic_error"),
        (Decimal("1E-6143"), "DIVIDE", "3", "decimal_arithmetic_error"),
    ],
)
def test_decimal_overflow_and_underflow_fail_deterministically(
    event_value: Decimal,
    operator: str,
    right: str,
    code: str,
) -> None:
    event = _event(
        Quote(
            instrument=_INSTRUMENT,
            timestamp=_NOW,
            last=event_value,
        )
    )
    definition = _flow(
        extra_nodes=(
            FlowNode("last", "event_field", (("field", "quote.last"),)),
            FlowNode("required", "require_decimal"),
            FlowNode("right", "decimal_constant", (("value", right),)),
            FlowNode("arithmetic", "decimal_binary", (("operator", operator),)),
            _intent_node(),
        ),
        extra_edges=(
            FlowEdge("last-required", "last", "value", "required", "value"),
            FlowEdge("required-arithmetic", "required", "value", "arithmetic", "left"),
            FlowEdge("right-arithmetic", "right", "value", "arithmetic", "right"),
            FlowEdge("arithmetic-intent", "arithmetic", "value", "intent", "quantity"),
        ),
        intent_source="intent",
    )

    with pytest.raises(FlowEvaluationError) as caught:
        _evaluate(definition, _context(event=event))

    assert caught.value.code == code
    assert caught.value.node_id == "arithmetic"


def test_confidence_conversion_occurs_only_at_existing_signal_boundary() -> None:
    result = _evaluate(_flow(confidence_value="0.125"))

    assert type(result.signal.confidence) is float
    assert result.signal.confidence == 0.125


def test_strategy_identity_and_version_must_match_context_ir() -> None:
    wrong_id_ir = StrategyIR(
        strategy_id=StrategyId("other"),
        version="1",
        name="Other",
        market_contexts=(),
        parameters=(),
    )
    wrong_version_ir = replace(_ir(), version="2")
    base = _context()
    wrong_id = StrategyContext(base.event, wrong_id_ir, as_of=base.as_of, engine=base.engine)
    wrong_version = StrategyContext(
        base.event,
        wrong_version_ir,
        as_of=base.as_of,
        engine=base.engine,
    )

    with pytest.raises(FlowEvaluationError, match="strategy_identity_mismatch"):
        _evaluate(_flow(), wrong_id)
    with pytest.raises(FlowEvaluationError, match="strategy_version_mismatch"):
        _evaluate(_flow(), wrong_version)


def test_interpreter_requires_a_current_market_event() -> None:
    context = StrategyContext(
        event=None,
        ir=_ir(),
        as_of=_NOW,
        engine=_snapshot(),
    )

    with pytest.raises(FlowEvaluationError, match="missing_market_event"):
        _evaluate(_flow(), context)


def test_plan_execution_has_no_wall_clock_random_or_io_capability_imports() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    source_root = repository_root / "src" / "quantx" / "strategy" / "flow"
    forbidden_import_roots = {
        "asyncio",
        "ctypes",
        "http",
        "importlib",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "threading",
        "time",
        "urllib",
    }
    forbidden_import_prefixes = (
        "quantx.application",
        "quantx.integrations",
        "quantx.persistence",
        "quantx.plugins",
        "quantx.ports",
    )
    forbidden_calls = {
        "__import__",
        "create_order",
        "eval",
        "exec",
        "open",
        "place_order",
        "send_order",
        "sleep",
        "submit_order",
        "urandom",
        "utcnow",
        "uuid1",
        "uuid4",
    }

    for source_path in sorted(source_root.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".", maxsplit=1)[0] not in forbidden_import_roots
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                assert node.module.split(".", maxsplit=1)[0] not in forbidden_import_roots
                assert not node.module.startswith(forbidden_import_prefixes)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden_calls
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in forbidden_calls | {"now"}
    float_calls = [
        node
        for source_path in sorted(source_root.glob("*.py"))
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    assert len(float_calls) == 1
    assert isinstance(float_calls[0].args[0], ast.Name)
    assert float_calls[0].args[0].id == "confidence_decimal"
