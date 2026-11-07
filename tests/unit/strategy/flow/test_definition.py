from dataclasses import FrozenInstanceError

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import StrategyId
from quantx.strategy.flow import (
    MAX_FLOW_PARAMETER_LENGTH,
    FlowDefinition,
    FlowEdge,
    FlowNode,
)


def _context(family: MarketFamily = MarketFamily.EQUITY) -> MarketContext:
    venue = "NSE" if family is MarketFamily.EQUITY else "NFO"
    return MarketContext(MarketRegion.INDIA, family, venue, "IN")


def _definition(
    *,
    nodes: tuple[FlowNode, ...] | None = None,
    edges: tuple[FlowEdge, ...] | None = None,
    contexts: tuple[MarketContext, ...] | None = None,
    schema_version: int = 1,
    compiler_contract_version: str = "1",
) -> FlowDefinition:
    return FlowDefinition(
        strategy_id=StrategyId("mean-reversion"),
        version="1.2.0",
        name="Mean Reversion",
        market_contexts=(_context(),) if contexts is None else contexts,
        nodes=(
            FlowNode("action", "signal_action_constant", (("value", "BUY"),)),
            FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        )
        if nodes is None
        else nodes,
        edges=() if edges is None else edges,
        schema_version=schema_version,
        compiler_contract_version=compiler_contract_version,
    )


def test_flow_nodes_reject_mutable_or_noncanonical_parameter_collections() -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        FlowNode("node", "string_constant", [("value", "entry")])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="name/value tuples"):
        FlowNode("node", "string_constant", (["value", "entry"],))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="sorted"):
        FlowNode("node", "string_constant", (("z", "1"), ("a", "2")))

    with pytest.raises(ValueError, match="unique"):
        FlowNode("node", "string_constant", (("value", "1"), ("value", "2")))


def test_flow_node_parameter_values_have_a_fixed_size_bound() -> None:
    with pytest.raises(ValueError, match="maximum length"):
        FlowNode(
            "node",
            "string_constant",
            (("value", "x" * (MAX_FLOW_PARAMETER_LENGTH + 1)),),
        )


def test_flow_edge_rejects_empty_endpoint_identity() -> None:
    with pytest.raises(ValueError, match="target_port"):
        FlowEdge("edge", "source", "value", "target", " ")


def test_flow_definition_requires_immutable_typed_collections() -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        _definition(
            nodes=[
                FlowNode("action", "signal_action_constant", (("value", "BUY"),))
            ]  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="MarketContext"):
        _definition(contexts=("NSE",))  # type: ignore[arg-type]


def test_flow_definition_is_frozen_and_canonical_identity_ignores_graph_order() -> None:
    action = FlowNode("action", "signal_action_constant", (("value", "BUY"),))
    confidence = FlowNode("confidence", "confidence_constant", (("value", "0.75"),))
    reason = FlowNode("reason", "string_constant", (("value", "entry"),))
    result = FlowNode("result", "strategy_result")
    edges = (
        FlowEdge("e1", "action", "value", "result", "action"),
        FlowEdge("e2", "confidence", "value", "result", "confidence"),
        FlowEdge("e3", "reason", "value", "result", "reason"),
    )
    first = _definition(
        nodes=(action, confidence, reason, result),
        edges=edges,
        contexts=(_context(), _context(MarketFamily.DERIVATIVES)),
    )
    second = _definition(
        nodes=(result, reason, confidence, action),
        edges=tuple(reversed(edges)),
        contexts=(_context(MarketFamily.DERIVATIVES), _context()),
    )

    assert first.canonical_json() == second.canonical_json()
    assert first.fingerprint == second.fingerprint
    with pytest.raises(FrozenInstanceError):
        first.name = "mutated"  # type: ignore[misc]



def test_market_context_fingerprint_uses_canonical_venue_and_country_text() -> None:
    canonical = _context()
    equivalent = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, " NSE ", "in")

    first = _definition(contexts=(canonical,))
    second = _definition(contexts=(equivalent,))

    assert first.fingerprint == second.fingerprint


def test_canonical_identity_changes_for_behavior_or_contract_version_changes() -> None:
    base = _definition()
    changed_node = _definition(
        nodes=(
            FlowNode("action", "signal_action_constant", (("value", "SELL"),)),
            FlowNode("confidence", "confidence_constant", (("value", "0.75"),)),
        )
    )
    changed_schema = _definition(schema_version=2)
    changed_compiler = _definition(compiler_contract_version="2")

    fingerprints = {
        base.fingerprint,
        changed_node.fingerprint,
        changed_schema.fingerprint,
        changed_compiler.fingerprint,
    }
    assert len(fingerprints) == 4


def test_canonical_payload_is_a_fresh_mutable_copy_not_definition_state() -> None:
    definition = _definition()
    fingerprint = definition.fingerprint
    payload = definition.canonical_payload()
    payload["nodes"].clear()  # type: ignore[union-attr]

    assert definition.fingerprint == fingerprint
    assert len(definition.nodes) == 2
