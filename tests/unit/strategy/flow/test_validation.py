"""Deterministic graph integrity checks for the v1 Flow contract."""

from dataclasses import replace
from decimal import Decimal

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import StrategyId
from quantx.strategy.flow import (
    FLOW_NODE_SPECS,
    FlowDefinition,
    FlowDefinitionValidationError,
    FlowDefinitionValidator,
    FlowEdge,
    FlowNode,
    FlowNodeKind,
    FlowNodeSpec,
    FlowParameterSpec,
    FlowParameterType,
    FlowPortSpec,
    FlowValueType,
)


def _base_nodes() -> tuple[FlowNode, ...]:
    return (
        FlowNode("action", "signal_action_constant", (("value", "BUY"),)),
        FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        FlowNode("reason", "string_constant", (("value", "entry"),)),
        FlowNode("quantity", "decimal_constant", (("value", "1"),)),
        FlowNode(
            "intent",
            "trade_intent",
            (("order_type", "MARKET"), ("side", "BUY"), ("time_in_force", "DAY")),
        ),
        FlowNode("result", "strategy_result"),
    )


def _base_edges() -> tuple[FlowEdge, ...]:
    return (
        FlowEdge("e-action", "action", "value", "result", "action"),
        FlowEdge("e-confidence", "confidence", "value", "result", "confidence"),
        FlowEdge("e-reason", "reason", "value", "result", "reason"),
        FlowEdge("e-quantity", "quantity", "value", "intent", "quantity"),
        FlowEdge("e-intent", "intent", "intent", "result", "intent"),
    )


def _definition(
    *,
    nodes: tuple[FlowNode, ...] | None = None,
    edges: tuple[FlowEdge, ...] | None = None,
    schema_version: int = 1,
    compiler_contract_version: str = "1",
    contexts: tuple[MarketContext, ...] = (),
) -> FlowDefinition:
    return FlowDefinition(
        strategy_id=StrategyId("sample-flow"),
        version="1",
        name="Sample Flow",
        market_contexts=contexts,
        nodes=_base_nodes() if nodes is None else nodes,
        edges=_base_edges() if edges is None else edges,
        schema_version=schema_version,
        compiler_contract_version=compiler_contract_version,
    )


def _codes(definition: FlowDefinition) -> set[str]:
    result = FlowDefinitionValidator().validate(definition)
    return {issue.code for issue in result.issues}


def test_public_catalogue_specs_are_deeply_immutable_and_use_closed_types() -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        FlowParameterSpec("mode", FlowParameterType.CHOICE, ["BUY"])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="supported FlowValueType"):
        FlowPortSpec("output", "ARBITRARY")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="immutable tuple"):
        FlowNodeSpec(FlowNodeKind.BOOLEAN_NOT, [], (), ())  # type: ignore[arg-type]

    valid = FlowNodeSpec(
        FlowNodeKind.BOOLEAN_NOT,
        (),
        (FlowPortSpec("value", FlowValueType.BOOLEAN),),
        (FlowPortSpec("value", FlowValueType.BOOLEAN),),
    )
    assert valid.kind is FlowNodeKind.BOOLEAN_NOT


def test_closed_catalogue_accepts_minimal_typed_strategy_result_graph() -> None:
    result = FlowDefinitionValidator().validate(_definition())

    assert result.is_valid
    assert result.issues == ()


def test_catalogue_is_closed_and_trade_intent_is_not_an_order_action() -> None:
    assert FlowNodeKind.STRATEGY_RESULT in FLOW_NODE_SPECS
    assert all(type(kind) is str for kind in FLOW_NODE_SPECS)
    assert FlowNodeKind.TRADE_INTENT in FLOW_NODE_SPECS
    assert "place_order" not in FLOW_NODE_SPECS
    assert "submit_order" not in FLOW_NODE_SPECS
    assert FLOW_NODE_SPECS[FlowNodeKind.EVENT_FIELD].outputs[0].value_type == (
        FlowValueType.OPTIONAL_DECIMAL
    )
    assert FLOW_NODE_SPECS[FlowNodeKind.PRIOR_CANDLE_FIELD].outputs[0].value_type == (
        FlowValueType.OPTIONAL_DECIMAL
    )
    assert FLOW_NODE_SPECS[FlowNodeKind.ENGINE_POSITION_QUANTITY].outputs[0].value_type == (
        FlowValueType.OPTIONAL_DECIMAL
    )
    assert FLOW_NODE_SPECS[FlowNodeKind.ENGINE_ACTIVE_ORDER_EXISTS].outputs[0].value_type == (
        FlowValueType.OPTIONAL_BOOLEAN
    )


def test_validation_diagnostics_are_stable_under_node_and_edge_reordering() -> None:
    definition = _definition(
        nodes=(
            *_base_nodes(),
            FlowNode("unused", "decimal_constant", (("value", "2"),)),
        )
    )
    reordered = replace(
        definition,
        nodes=tuple(reversed(definition.nodes)),
        edges=tuple(reversed(definition.edges)),
    )

    first = FlowDefinitionValidator().validate(definition)
    second = FlowDefinitionValidator().validate(reordered)

    assert first.issues == second.issues
    assert "orphan_node" in {issue.code for issue in first.issues}


def test_validator_rejects_unknown_node_kinds_and_parameters() -> None:
    nodes = (
        *_base_nodes(),
        FlowNode("unknown", "python", (("code", "return 1"),)),
    )
    result = FlowDefinitionValidator().validate(_definition(nodes=nodes))
    codes = {issue.code for issue in result.issues}

    assert "unsupported_node_kind" in codes
    assert "orphan_node" in codes


def test_validator_rejects_missing_and_unexpected_node_parameters() -> None:
    nodes = (
        FlowNode("action", "signal_action_constant"),
        *_base_nodes()[1:],
    )
    missing = _codes(_definition(nodes=nodes))
    unexpected_nodes = (
        *_base_nodes()[:1],
        FlowNode("confidence", "confidence_constant", (("extra", "x"), ("value", "0.75"))),
        *_base_nodes()[2:],
    )
    unexpected = _codes(_definition(nodes=unexpected_nodes))

    assert "missing_parameter" in missing
    assert "unexpected_parameter" in unexpected


@pytest.mark.parametrize(
    "value",
    ["1.0", "01", "1e2", "-0", "NaN", "Infinity", "+1"],
)
def test_decimal_constants_require_finite_canonical_fixed_point_strings(value: str) -> None:
    nodes = (
        *_base_nodes()[:3],
        FlowNode("quantity", "decimal_constant", (("value", value),)),
        *_base_nodes()[4:],
    )

    assert "invalid_parameter" in _codes(_definition(nodes=nodes))


def test_large_decimal_constants_are_validated_without_context_rounding() -> None:
    value = "1234567890123456789012345678901234567890"
    nodes = (
        *_base_nodes()[:3],
        FlowNode("quantity", "decimal_constant", (("value", value),)),
        *_base_nodes()[4:],
    )

    assert "invalid_parameter" not in _codes(_definition(nodes=nodes))
    assert Decimal(value).is_finite()


@pytest.mark.parametrize("value", ["-0.1", "1.1", "1.00", "NaN"])
def test_confidence_constants_require_canonical_values_in_zero_to_one(value: str) -> None:
    nodes = (
        _base_nodes()[0],
        FlowNode("confidence", "confidence_constant", (("value", value),)),
        *_base_nodes()[2:],
    )

    assert "invalid_parameter" in _codes(_definition(nodes=nodes))


@pytest.mark.parametrize("value", ["True", "FALSE", "1", " true"])
def test_boolean_constants_accept_only_lowercase_boolean_lexemes(value: str) -> None:
    nodes = (*_base_nodes(), FlowNode("gate", "boolean_constant", (("value", value),)))
    result = FlowDefinitionValidator().validate(_definition(nodes=nodes))

    assert any(
        issue.code == "invalid_parameter" and issue.node_id == "gate" for issue in result.issues
    )


@pytest.mark.parametrize("bars_ago", ["0", "513", "-1", "01", "+1", "1.0"])
def test_prior_history_index_must_be_canonical_and_bounded(bars_ago: str) -> None:
    nodes = (
        *_base_nodes(),
        FlowNode(
            "history",
            "prior_candle_field",
            (("bars_ago", bars_ago), ("field", "close")),
        ),
    )

    assert "invalid_parameter" in _codes(_definition(nodes=nodes))


def test_event_field_and_prior_history_sources_use_closed_field_catalogues() -> None:
    nodes = (
        *_base_nodes(),
        FlowNode("event-price", "event_field", (("field", "quote.mid"),)),
        FlowNode(
            "history-close",
            "prior_candle_field",
            (("bars_ago", "1"), ("field", "close")),
        ),
    )
    result = FlowDefinitionValidator().validate(_definition(nodes=nodes))
    assert not any(issue.code == "invalid_parameter" for issue in result.issues)

    invalid_nodes = (
        *_base_nodes(),
        FlowNode("event-price", "event_field", (("field", "portfolio.equity"),)),
    )
    assert "invalid_parameter" in _codes(_definition(nodes=invalid_nodes))


def test_unsupported_schema_and_compiler_versions_fail_closed() -> None:
    result = FlowDefinitionValidator().validate(
        _definition(schema_version=2, compiler_contract_version="2")
    )
    codes = {issue.code for issue in result.issues}

    assert "unsupported_schema_version" in codes
    assert "unsupported_compiler_contract" in codes


def test_required_inputs_must_be_connected_and_orphans_are_reported() -> None:
    edges = tuple(edge for edge in _base_edges() if edge.edge_id != "e-reason")
    codes = _codes(_definition(edges=edges))

    assert "missing_required_input" in codes
    assert "orphan_node" in codes


def test_optional_intent_input_may_be_absent() -> None:
    nodes = tuple(node for node in _base_nodes() if node.node_id not in {"quantity", "intent"})
    edges = tuple(edge for edge in _base_edges() if edge.edge_id not in {"e-quantity", "e-intent"})

    assert FlowDefinitionValidator().validate(_definition(nodes=nodes, edges=edges)).is_valid


def test_input_port_rejects_multiple_incoming_connections() -> None:
    nodes = (
        *_base_nodes(),
        FlowNode("second-action", "signal_action_constant", (("value", "SELL"),)),
    )
    edges = (
        *_base_edges(),
        FlowEdge("e-action-duplicate", "second-action", "value", "result", "action"),
    )
    assert "duplicate_input_connection" in _codes(_definition(nodes=nodes, edges=edges))


def test_port_type_mismatch_is_rejected_without_coercion() -> None:
    edges = tuple(
        FlowEdge(edge.edge_id, "confidence", "value", "result", "action")
        if edge.edge_id == "e-action"
        else edge
        for edge in _base_edges()
    )
    assert "port_type_mismatch" in _codes(_definition(edges=edges))


def test_unknown_nodes_and_ports_are_rejected() -> None:
    edges = (
        *_base_edges(),
        FlowEdge("e-missing-source", "absent", "value", "result", "reason"),
        FlowEdge("e-missing-source-port", "action", "missing", "result", "action"),
        FlowEdge("e-missing-target-port", "confidence", "value", "result", "missing"),
    )
    codes = _codes(_definition(edges=edges))

    assert "unknown_source_node" in codes
    assert "unknown_source_port" in codes
    assert "unknown_target_port" in codes


def test_invalid_node_and_edge_identifier_lexemes_are_rejected() -> None:
    invalid_node = FlowNode("bad id", "decimal_constant", (("value", "1"),))
    nodes = (*_base_nodes(), invalid_node)
    edges = (
        *_base_edges(),
        FlowEdge("bad edge", "quantity", "value", "intent", "quantity"),
    )

    codes = _codes(_definition(nodes=nodes, edges=edges))

    assert "invalid_node_id" in codes
    assert "invalid_edge_id" in codes


def test_duplicate_node_and_edge_identities_are_rejected() -> None:
    nodes = (*_base_nodes(), FlowNode("action", "signal_action_constant", (("value", "SELL"),)))
    edges = (*_base_edges(), replace(_base_edges()[0], edge_id="e-confidence"))

    codes = _codes(_definition(nodes=nodes, edges=edges))

    assert "duplicate_node_id" in codes
    assert "duplicate_edge_id" in codes


def test_directed_cycles_are_rejected() -> None:
    nodes = (
        FlowNode("action", "signal_action_constant", (("value", "BUY"),)),
        FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        FlowNode("reason", "string_constant", (("value", "entry"),)),
        FlowNode("one", "decimal_constant", (("value", "1"),)),
        FlowNode("left", "decimal_binary", (("operator", "ADD"),)),
        FlowNode("right", "decimal_binary", (("operator", "SUBTRACT"),)),
        FlowNode(
            "intent",
            "trade_intent",
            (("order_type", "MARKET"), ("side", "BUY"), ("time_in_force", "DAY")),
        ),
        FlowNode("result", "strategy_result"),
    )
    edges = (
        FlowEdge("e-action", "action", "value", "result", "action"),
        FlowEdge("e-confidence", "confidence", "value", "result", "confidence"),
        FlowEdge("e-reason", "reason", "value", "result", "reason"),
        FlowEdge("e-one-left", "one", "value", "left", "right"),
        FlowEdge("e-one-right", "one", "value", "right", "right"),
        FlowEdge("e-left-right", "right", "value", "left", "left"),
        FlowEdge("e-right-left", "left", "value", "right", "left"),
        FlowEdge("e-intent", "intent", "intent", "result", "intent"),
        FlowEdge("e-quantity", "left", "value", "intent", "quantity"),
    )

    assert "cycle_detected" in _codes(_definition(nodes=nodes, edges=edges))


def test_all_executable_nodes_must_reach_the_single_strategy_result() -> None:
    nodes = (*_base_nodes(), FlowNode("unused", "decimal_constant", (("value", "9"),)))
    assert "orphan_node" in _codes(_definition(nodes=nodes))


def test_flow_requires_exactly_one_terminal_strategy_result() -> None:
    nodes = (*_base_nodes(), FlowNode("second-result", "strategy_result"))
    assert "multiple_strategy_results" in _codes(_definition(nodes=nodes))

    edges = (*_base_edges(), FlowEdge("e-out", "result", "result", "reason", "value"))
    assert "strategy_result_has_outgoing_edge" in _codes(_definition(edges=edges))


def test_duplicate_market_contexts_are_rejected_after_canonical_text_normalization() -> None:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    equivalent = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, " NSE ", "in")
    assert "duplicate_market_context" in _codes(_definition(contexts=(market, equivalent)))


@pytest.mark.parametrize(
    ("nodes", "edges", "expected_code"),
    [
        (
            tuple(
                FlowNode(f"node-{index}", "decimal_constant", (("value", "1"),))
                for index in range(257)
            ),
            (),
            "node_limit_exceeded",
        ),
        (
            _base_nodes(),
            tuple(
                FlowEdge(f"edge-{index}", "quantity", "value", "intent", "quantity")
                for index in range(1025)
            ),
            "edge_limit_exceeded",
        ),
    ],
)
def test_graph_resource_limits_fail_closed_without_graph_traversal(
    nodes: tuple[FlowNode, ...],
    edges: tuple[FlowEdge, ...],
    expected_code: str,
) -> None:
    result = FlowDefinitionValidator().validate(_definition(nodes=nodes, edges=edges))

    assert {issue.code for issue in result.issues} == {expected_code}


def test_validation_result_raises_with_stable_issues() -> None:
    result = FlowDefinitionValidator().validate(_definition(schema_version=2))

    with pytest.raises(FlowDefinitionValidationError, match="unsupported_schema_version"):
        result.raise_for_errors()
