"""Pure fail-closed validation for immutable declarative Flow definitions."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .catalog import (
    FLOW_NODE_SPECS,
    MAX_FLOW_EDGES,
    MAX_FLOW_HISTORY_BARS,
    MAX_FLOW_NODES,
    FlowNodeSpec,
    FlowParameterSpec,
    FlowParameterType,
)
from .definition import (
    FLOW_COMPILER_CONTRACT_VERSION,
    FLOW_SCHEMA_VERSION,
    FlowDefinition,
    FlowNode,
)

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_IssueAdder = Callable[..., None]


@dataclass(frozen=True, slots=True)
class FlowValidationIssue:
    """One deterministic, location-aware graph validation diagnostic."""

    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("flow validation issue code must not be empty")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("flow validation issue message must not be empty")
        for field_name in ("node_id", "edge_id", "field"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"flow validation issue {field_name} must be a string or None")


@dataclass(frozen=True, slots=True)
class FlowValidationResult:
    """Immutable validation outcome; no evaluator or external side effects."""

    issues: tuple[FlowValidationIssue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.issues, tuple):
            raise TypeError("flow validation issues must be an immutable tuple")
        if any(not isinstance(item, FlowValidationIssue) for item in self.issues):
            raise TypeError("flow validation issues must contain FlowValidationIssue values")

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.issues:
            raise FlowDefinitionValidationError(self.issues)


class FlowDefinitionValidationError(ValueError):
    """Raised when a caller requires a valid graph before compilation."""

    def __init__(self, issues: tuple[FlowValidationIssue, ...]) -> None:
        self.issues = issues
        summary = "; ".join(f"{item.code}: {item.message}" for item in issues)
        super().__init__(summary)


class FlowDefinitionValidator:
    """Validate graph shape, closed catalogue, types, acyclicity and reachability."""

    def validate(self, definition: FlowDefinition) -> FlowValidationResult:
        if not isinstance(definition, FlowDefinition):
            raise TypeError("definition must be a FlowDefinition")

        issues: list[FlowValidationIssue] = []

        def add(
            code: str,
            message: str,
            *,
            node_id: str | None = None,
            edge_id: str | None = None,
            field: str | None = None,
        ) -> None:
            issues.append(
                FlowValidationIssue(
                    code=code,
                    message=message,
                    node_id=node_id,
                    edge_id=edge_id,
                    field=field,
                )
            )

        if definition.schema_version != FLOW_SCHEMA_VERSION:
            add(
                "unsupported_schema_version",
                f"schema version {definition.schema_version} is not supported",
                field="schema_version",
            )
        if definition.compiler_contract_version != FLOW_COMPILER_CONTRACT_VERSION:
            add(
                "unsupported_compiler_contract",
                "compiler contract version is not supported",
                field="compiler_contract_version",
            )

        context_keys: set[tuple[str, str, str, str | None]] = set()
        for context in definition.market_contexts:
            key = (
                context.region.value,
                context.family.value,
                context.venue,
                context.country_code,
            )
            if key in context_keys:
                add("duplicate_market_context", "market context is duplicated")
            context_keys.add(key)

        if len(definition.nodes) > MAX_FLOW_NODES:
            add(
                "node_limit_exceeded",
                f"flow contains more than {MAX_FLOW_NODES} nodes",
                field="nodes",
            )
        if len(definition.edges) > MAX_FLOW_EDGES:
            add(
                "edge_limit_exceeded",
                f"flow contains more than {MAX_FLOW_EDGES} edges",
                field="edges",
            )
        if not definition.nodes:
            add("missing_nodes", "flow must contain at least one node", field="nodes")

        # Stop graph construction when a declared resource bound is exceeded.
        # The limit diagnostic is sufficient; traversal would defeat the bound.
        if len(definition.nodes) > MAX_FLOW_NODES or len(definition.edges) > MAX_FLOW_EDGES:
            ordered_issues = tuple(
                sorted(
                    issues,
                    key=lambda item: (
                        item.code,
                        item.node_id or "",
                        item.edge_id or "",
                        item.field or "",
                        item.message,
                    ),
                )
            )
            return FlowValidationResult(ordered_issues)

        node_counts: dict[str, int] = defaultdict(int)
        for node in definition.nodes:
            node_counts[node.node_id] += 1
        for node_id, count in sorted(node_counts.items()):
            if count > 1:
                add(
                    "duplicate_node_id",
                    f"node id {node_id!r} is used {count} times",
                    node_id=node_id,
                )

        node_map: dict[str, FlowNode] = {
            node.node_id: node
            for node in definition.nodes
            if node_counts[node.node_id] == 1
        }
        node_specs: dict[str, FlowNodeSpec] = {}
        for node in sorted(definition.nodes, key=lambda item: (item.node_id, item.kind)):
            if not _ID.fullmatch(node.node_id):
                add(
                    "invalid_node_id",
                    "node id must start with an ASCII letter and contain only letters, digits, "
                    "underscore or hyphen (maximum 64 characters)",
                    node_id=node.node_id,
                    field="node_id",
                )
            if node_counts[node.node_id] != 1:
                continue
            spec = FLOW_NODE_SPECS.get(node.kind)
            if spec is None:
                add(
                    "unsupported_node_kind",
                    f"node kind {node.kind!r} is not supported by Flow v1",
                    node_id=node.node_id,
                    field="kind",
                )
                continue
            node_specs[node.node_id] = spec
            _validate_node_parameters(node, spec.parameters, add)

        edge_counts: dict[str, int] = defaultdict(int)
        for edge in definition.edges:
            edge_counts[edge.edge_id] += 1
        for edge_id, count in sorted(edge_counts.items()):
            if count > 1:
                add(
                    "duplicate_edge_id",
                    f"edge id {edge_id!r} is used {count} times",
                    edge_id=edge_id,
                )

        incoming: dict[tuple[str, str], int] = defaultdict(int)
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_map}
        reverse_adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_map}

        for edge in sorted(
            definition.edges,
            key=lambda item: (
                item.edge_id,
                item.source_node_id,
                item.source_port,
                item.target_node_id,
                item.target_port,
            ),
        ):
            if not _ID.fullmatch(edge.edge_id):
                add(
                    "invalid_edge_id",
                    "edge id must start with an ASCII letter and contain only letters, digits, "
                    "underscore or hyphen (maximum 64 characters)",
                    edge_id=edge.edge_id,
                    field="edge_id",
                )
            source = node_map.get(edge.source_node_id)
            target = node_map.get(edge.target_node_id)
            if source is None:
                add(
                    "unknown_source_node",
                    f"source node {edge.source_node_id!r} does not resolve uniquely",
                    edge_id=edge.edge_id,
                    field="source_node_id",
                )
            if target is None:
                add(
                    "unknown_target_node",
                    f"target node {edge.target_node_id!r} does not resolve uniquely",
                    edge_id=edge.edge_id,
                    field="target_node_id",
                )
            if source is not None and target is not None:
                adjacency[source.node_id].add(target.node_id)
                reverse_adjacency[target.node_id].add(source.node_id)

            source_spec = node_specs.get(edge.source_node_id)
            target_spec = node_specs.get(edge.target_node_id)
            output = (
                None
                if source_spec is None
                else next(
                    (port for port in source_spec.outputs if port.name == edge.source_port),
                    None,
                )
            )
            input_port = (
                None
                if target_spec is None
                else next(
                    (port for port in target_spec.inputs if port.name == edge.target_port),
                    None,
                )
            )
            if source_spec is not None and output is None:
                add(
                    "unknown_source_port",
                    f"output port {edge.source_port!r} does not exist on node "
                    f"{edge.source_node_id!r}",
                    edge_id=edge.edge_id,
                    node_id=edge.source_node_id,
                    field="source_port",
                )
            if target_spec is not None and input_port is None:
                add(
                    "unknown_target_port",
                    f"input port {edge.target_port!r} does not exist on node "
                    f"{edge.target_node_id!r}",
                    edge_id=edge.edge_id,
                    node_id=edge.target_node_id,
                    field="target_port",
                )
            if input_port is not None:
                incoming[(edge.target_node_id, edge.target_port)] += 1
            if output is not None and input_port is not None:
                if output.value_type != input_port.value_type:
                    add(
                        "port_type_mismatch",
                        f"{edge.source_node_id}.{edge.source_port} has type "
                        f"{output.value_type}, expected {input_port.value_type} at "
                        f"{edge.target_node_id}.{edge.target_port}",
                        edge_id=edge.edge_id,
                        node_id=edge.target_node_id,
                    )

        for node_id, spec in sorted(node_specs.items()):
            for port in spec.inputs:
                count = incoming[(node_id, port.name)]
                if count > 1:
                    add(
                        "duplicate_input_connection",
                        f"input {port.name!r} has {count} incoming edges; at most one is allowed",
                        node_id=node_id,
                        field=port.name,
                    )
                elif port.required and count == 0:
                    add(
                        "missing_required_input",
                        f"required input {port.name!r} is not connected",
                        node_id=node_id,
                        field=port.name,
                    )

        result_nodes = sorted(
            node.node_id
            for node in definition.nodes
            if node.kind == "strategy_result"
        )
        if not result_nodes:
            add("missing_strategy_result", "flow must contain exactly one strategy_result node")
        elif len(result_nodes) > 1:
            add(
                "multiple_strategy_results",
                "flow must contain exactly one strategy_result node",
            )
        for edge in definition.edges:
            if edge.source_node_id in result_nodes:
                add(
                    "strategy_result_has_outgoing_edge",
                    "strategy_result must be the terminal graph output",
                    node_id=edge.source_node_id,
                    edge_id=edge.edge_id,
                )

        _validate_acyclic(node_map, adjacency, add)
        if len(result_nodes) == 1 and result_nodes[0] in reverse_adjacency:
            reachable: set[str] = set()
            pending = [result_nodes[0]]
            while pending:
                current = pending.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                pending.extend(sorted(reverse_adjacency[current] - reachable, reverse=True))
            for node_id in sorted(set(node_map) - reachable):
                add(
                    "orphan_node",
                    "node does not contribute to the strategy_result output",
                    node_id=node_id,
                )

        ordered_issues = tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.code,
                    item.node_id or "",
                    item.edge_id or "",
                    item.field or "",
                    item.message,
                ),
            )
        )
        return FlowValidationResult(ordered_issues)


def _validate_node_parameters(
    node: FlowNode,
    parameter_specs: tuple[FlowParameterSpec, ...],
    add: _IssueAdder,
) -> None:
    expected = {item.name: item for item in parameter_specs}
    provided = {name: value for name, value in node.parameters}
    for name in sorted(set(provided) - set(expected)):
        add(
            "unexpected_parameter",
            f"parameter {name!r} is not supported by node kind {node.kind!r}",
            node_id=node.node_id,
            field=name,
        )
    for name, spec in sorted(expected.items()):
        if name not in provided:
            add(
                "missing_parameter",
                f"required parameter {name!r} is missing",
                node_id=node.node_id,
                field=name,
            )
            continue
        error = _parameter_error(provided[name], spec)
        if error is not None:
            add(
                "invalid_parameter",
                error,
                node_id=node.node_id,
                field=name,
            )


def _canonical_fixed_point(value: Decimal) -> str:
    """Render fixed-point Decimal text without context rounding."""
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _parameter_error(value: str, spec: FlowParameterSpec) -> str | None:
    if spec.value_type is FlowParameterType.STRING:
        return None
    if spec.value_type is FlowParameterType.BOOLEAN:
        if value not in {"true", "false"}:
            return f"parameter {spec.name!r} must be exactly 'true' or 'false'"
        return None
    if spec.value_type is FlowParameterType.CHOICE:
        if value not in spec.choices:
            return f"parameter {spec.name!r} must be one of {', '.join(spec.choices)}"
        return None
    if spec.value_type in {FlowParameterType.DECIMAL, FlowParameterType.CONFIDENCE}:
        if not _DECIMAL.fullmatch(value):
            return f"parameter {spec.name!r} must be a canonical fixed-point decimal string"
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return f"parameter {spec.name!r} is not a valid Decimal"
        if not parsed.is_finite() or _canonical_fixed_point(parsed) != value:
            return f"parameter {spec.name!r} must be finite and canonically encoded"
        if spec.value_type is FlowParameterType.CONFIDENCE and not (
            Decimal("0") <= parsed <= Decimal("1")
        ):
            return f"parameter {spec.name!r} must be between 0 and 1 inclusive"
        return None
    if spec.value_type is FlowParameterType.INTEGER:
        if not _INTEGER.fullmatch(value):
            return f"parameter {spec.name!r} must be a canonical integer string"
        parsed_integer = int(value)
        if spec.minimum is not None and parsed_integer < spec.minimum:
            return f"parameter {spec.name!r} must be at least {spec.minimum}"
        if spec.maximum is not None and parsed_integer > spec.maximum:
            return f"parameter {spec.name!r} must be at most {spec.maximum}"
        if spec.name == "bars_ago" and parsed_integer > MAX_FLOW_HISTORY_BARS:
            return f"parameter {spec.name!r} must be at most {MAX_FLOW_HISTORY_BARS}"
        return None
    return f"parameter {spec.name!r} has an unsupported parameter type"


def _validate_acyclic(
    nodes: dict[str, FlowNode],
    adjacency: dict[str, set[str]],
    add: _IssueAdder,
) -> None:
    indegree = {node_id: 0 for node_id in nodes}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited: set[str] = set()
    while ready:
        node_id = ready.popleft()
        visited.add(node_id)
        for target in sorted(adjacency[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(visited) != len(nodes):
        cycle_nodes = sorted(set(nodes) - visited)
        add(
            "cycle_detected",
            f"flow contains a directed cycle involving nodes: {', '.join(cycle_nodes)}",
        )
