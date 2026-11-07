"""Deterministic compilation of validated Flow v1 graphs into immutable plans."""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass, replace

from .definition import (
    FLOW_COMPILER_CONTRACT_VERSION,
    FLOW_DECIMAL_CONTRACT_VERSION,
    FlowDefinition,
    FlowNode,
)
from .validation import FlowDefinitionValidator


@dataclass(frozen=True, slots=True)
class FlowInputBinding:
    """One immutable connection from a source output to a target input."""

    input_port: str
    source_node_id: str
    source_port: str

    def __post_init__(self) -> None:
        for name in ("input_port", "source_node_id", "source_port"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Flow input binding {name} must not be empty")


@dataclass(frozen=True, slots=True)
class FlowInstruction:
    """One node and its deterministically ordered input bindings."""

    node: FlowNode
    inputs: tuple[FlowInputBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.node, FlowNode):
            raise TypeError("Flow instruction node must be a FlowNode")
        if not isinstance(self.inputs, tuple):
            raise TypeError("Flow instruction inputs must be an immutable tuple")
        if any(not isinstance(item, FlowInputBinding) for item in self.inputs):
            raise TypeError("Flow instruction inputs must contain FlowInputBinding values")
        ports = tuple(item.input_port for item in self.inputs)
        if ports != tuple(sorted(ports)) or len(ports) != len(set(ports)):
            raise ValueError("Flow instruction inputs must have unique sorted ports")


@dataclass(frozen=True, slots=True)
class FlowExecutionPlan:
    """Immutable compiled graph with a version-bound deterministic fingerprint.

    The plan retains the validated definition so an interpreter can independently
    verify that a caller has not fabricated or altered the instruction sequence.
    """

    definition: FlowDefinition
    instructions: tuple[FlowInstruction, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition, FlowDefinition):
            raise TypeError("Flow execution plan definition must be a FlowDefinition")
        if not isinstance(self.instructions, tuple):
            raise TypeError("Flow execution plan instructions must be an immutable tuple")
        if any(not isinstance(item, FlowInstruction) for item in self.instructions):
            raise TypeError("Flow execution plan instructions have an invalid item")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.startswith("sha256:"):
            raise ValueError("Flow execution plan fingerprint must be a SHA-256 identity")

    @property
    def plan_id(self) -> str:
        """Return the stable fingerprint used to identify this compiled plan."""
        return self.fingerprint


class FlowCompiler:
    """Validate and compile Flow v1 definitions without executing graph nodes."""

    def compile(self, definition: FlowDefinition) -> FlowExecutionPlan:
        """Return a stable topological plan; invalid definitions never compile."""
        validation = FlowDefinitionValidator().validate(definition)
        validation.raise_for_errors()

        # Keep a canonical definition in the plan, not only a canonical
        # fingerprint, so equivalent input tuple orders produce equal values.
        canonical_definition = replace(
            definition,
            nodes=tuple(
                sorted(
                    definition.nodes,
                    key=lambda node: (node.node_id, node.kind, node.parameters),
                )
            ),
            edges=tuple(
                sorted(
                    definition.edges,
                    key=lambda edge: (
                        edge.edge_id,
                        edge.source_node_id,
                        edge.source_port,
                        edge.target_node_id,
                        edge.target_port,
                    ),
                )
            ),
        )
        node_map = {node.node_id: node for node in canonical_definition.nodes}
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_map}
        indegree = {node_id: 0 for node_id in node_map}
        bindings: dict[str, list[FlowInputBinding]] = {node_id: [] for node_id in node_map}

        for edge in canonical_definition.edges:
            bindings[edge.target_node_id].append(
                FlowInputBinding(
                    input_port=edge.target_port,
                    source_node_id=edge.source_node_id,
                    source_port=edge.source_port,
                )
            )
            if edge.target_node_id not in adjacency[edge.source_node_id]:
                adjacency[edge.source_node_id].add(edge.target_node_id)
                indegree[edge.target_node_id] += 1

        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        ordered_ids: list[str] = []
        while ready:
            node_id = heapq.heappop(ready)
            ordered_ids.append(node_id)
            for target_id in sorted(adjacency[node_id]):
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    heapq.heappush(ready, target_id)

        # The validator rejects cycles. Retain a defensive check at this boundary
        # so a future validator regression cannot produce a partial plan.
        if len(ordered_ids) != len(node_map):
            raise ValueError("validated Flow graph did not produce a complete topological order")

        instructions = tuple(
            FlowInstruction(
                node=node_map[node_id],
                inputs=tuple(sorted(bindings[node_id], key=lambda item: item.input_port)),
            )
            for node_id in ordered_ids
        )
        payload = {
            "compiler_contract_version": FLOW_COMPILER_CONTRACT_VERSION,
            "decimal_contract_version": FLOW_DECIMAL_CONTRACT_VERSION,
            "definition_fingerprint": canonical_definition.fingerprint,
            "instructions": [
                {
                    "node_id": instruction.node.node_id,
                    "kind": instruction.node.kind,
                    "inputs": [
                        {
                            "input_port": binding.input_port,
                            "source_node_id": binding.source_node_id,
                            "source_port": binding.source_port,
                        }
                        for binding in instruction.inputs
                    ],
                }
                for instruction in instructions
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        fingerprint = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        return FlowExecutionPlan(
            definition=canonical_definition,
            instructions=instructions,
            fingerprint=fingerprint,
        )


__all__ = [
    "FlowCompiler",
    "FlowExecutionPlan",
    "FlowInputBinding",
    "FlowInstruction",
]
