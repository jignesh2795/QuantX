"""Immutable declarative strategy Flow graph definitions and canonical identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import StrategyId

FLOW_SCHEMA_VERSION = 1
FLOW_COMPILER_CONTRACT_VERSION = "1"
MAX_FLOW_PARAMETER_LENGTH = 512


class FlowNodeKind(StrEnum):
    """Closed v1 node-kind names; unknown strings remain representable for validation."""

    EVENT_FIELD = "event_field"
    PRIOR_CANDLE_FIELD = "prior_candle_field"
    ENGINE_POSITION_QUANTITY = "engine_position_quantity"
    ENGINE_ACTIVE_ORDER_EXISTS = "engine_active_order_exists"
    DECIMAL_CONSTANT = "decimal_constant"
    CONFIDENCE_CONSTANT = "confidence_constant"
    BOOLEAN_CONSTANT = "boolean_constant"
    STRING_CONSTANT = "string_constant"
    SIGNAL_ACTION_CONSTANT = "signal_action_constant"
    DECIMAL_BINARY = "decimal_binary"
    DECIMAL_COMPARE = "decimal_compare"
    BOOLEAN_BINARY = "boolean_binary"
    BOOLEAN_NOT = "boolean_not"
    IS_AVAILABLE_DECIMAL = "is_available_decimal"
    IS_AVAILABLE_BOOLEAN = "is_available_boolean"
    REQUIRE_DECIMAL = "require_decimal"
    REQUIRE_BOOLEAN = "require_boolean"
    SELECT_DECIMAL = "select_decimal"
    ACTION_SELECT = "action_select"
    TRADE_INTENT = "trade_intent"
    STRATEGY_RESULT = "strategy_result"


class FlowValueType(StrEnum):
    """Wire-stable value kinds exchanged across graph ports."""

    DECIMAL = "DECIMAL"
    OPTIONAL_DECIMAL = "OPTIONAL_DECIMAL"
    BOOLEAN = "BOOLEAN"
    OPTIONAL_BOOLEAN = "OPTIONAL_BOOLEAN"
    STRING = "STRING"
    SIGNAL_ACTION = "SIGNAL_ACTION"
    CONFIDENCE = "CONFIDENCE"
    TRADE_INTENT = "TRADE_INTENT"
    STRATEGY_RESULT = "STRATEGY_RESULT"


@dataclass(frozen=True, slots=True)
class FlowNode:
    """One immutable, declarative node with sorted string parameters."""

    node_id: str
    kind: str
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("flow node id must not be empty")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("flow node kind must not be empty")
        if len(self.node_id) > 64 or len(self.kind) > 64:
            raise ValueError("flow node id and kind must not exceed 64 characters")
        if not isinstance(self.parameters, tuple):
            raise TypeError("flow node parameters must be an immutable tuple")
        if len(self.parameters) > 16:
            raise ValueError("flow node must not contain more than 16 parameters")
        keys: list[str] = []
        for parameter in self.parameters:
            if not isinstance(parameter, tuple) or len(parameter) != 2:
                raise TypeError("flow node parameters must contain name/value tuples")
            name, value = parameter
            if not isinstance(name, str) or not name.strip():
                raise ValueError("flow node parameter name must not be empty")
            if len(name) > 64:
                raise ValueError("flow node parameter names must not exceed 64 characters")
            if not isinstance(value, str):
                raise TypeError("flow node parameter values must be strings")
            if len(value) > MAX_FLOW_PARAMETER_LENGTH:
                raise ValueError(
                    "flow node parameter values exceed maximum length "
                    f"of {MAX_FLOW_PARAMETER_LENGTH} characters"
                )
            keys.append(name)
        if keys != sorted(keys):
            raise ValueError("flow node parameters must be sorted by name")
        if len(keys) != len(set(keys)):
            raise ValueError("flow node parameter names must be unique")


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """One immutable directed connection between two named node ports."""

    edge_id: str
    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str

    def __post_init__(self) -> None:
        for field_name in (
            "edge_id",
            "source_node_id",
            "source_port",
            "target_node_id",
            "target_port",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"flow edge {field_name} must not be empty")
            if len(value) > 64:
                raise ValueError(f"flow edge {field_name} must not exceed 64 characters")


@dataclass(frozen=True, slots=True)
class FlowDefinition:
    """Versioned graph content, independent of runtime, broker, and execution state.

    Nodes, edges, market contexts and parameters are immutable tuples. Graph
    structure is deliberately separate from StrategyIR's canonical string
    parameter tuple. Canonical JSON sorts unordered graph collections so
    equivalent definitions have one stable SHA-256 identity.
    """

    strategy_id: StrategyId
    version: str
    name: str
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]
    market_contexts: tuple[MarketContext, ...] = ()
    schema_version: int = FLOW_SCHEMA_VERSION
    compiler_contract_version: str = FLOW_COMPILER_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, StrategyId):
            raise TypeError("flow strategy_id must be a StrategyId")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("flow strategy version must not be empty")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("flow strategy name must not be empty")
        if len(self.version) > 128 or len(self.name) > 128:
            raise ValueError("flow strategy version and name must not exceed 128 characters")
        if len(self.strategy_id.value) > 128:
            raise ValueError("flow strategy id must not exceed 128 characters")
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("flow schema_version must be a positive integer")
        if (
            not isinstance(self.compiler_contract_version, str)
            or not self.compiler_contract_version.strip()
        ):
            raise ValueError("flow compiler contract version must not be empty")
        if len(self.compiler_contract_version) > 32:
            raise ValueError("flow compiler contract version must not exceed 32 characters")
        if not isinstance(self.market_contexts, tuple):
            raise TypeError("flow market_contexts must be an immutable tuple")
        if len(self.market_contexts) > 16:
            raise ValueError("flow must not contain more than 16 market contexts")
        if any(not isinstance(item, MarketContext) for item in self.market_contexts):
            raise TypeError("flow market_contexts must contain MarketContext values")
        if any(
            not isinstance(item.region, MarketRegion) or not isinstance(item.family, MarketFamily)
            for item in self.market_contexts
        ):
            raise TypeError("flow market contexts must use MarketRegion and MarketFamily enums")
        normalized_contexts: list[MarketContext] = []
        for item in self.market_contexts:
            venue = item.venue.strip()
            country_code = None if item.country_code is None else item.country_code.strip().upper()
            if country_code is not None and (
                len(country_code) != 2 or not country_code.isascii() or not country_code.isalpha()
            ):
                raise ValueError("flow country_code must be a two-letter ASCII alpha-2 code")
            normalized_contexts.append(
                MarketContext(
                    region=item.region,
                    family=item.family,
                    venue=venue,
                    country_code=country_code,
                )
            )
        region_order = {region: index for index, region in enumerate(MarketRegion)}
        family_order = {family: index for index, family in enumerate(MarketFamily)}
        normalized_contexts.sort(
            key=lambda item: (
                region_order[item.region],
                family_order[item.family],
                item.venue,
                "" if item.country_code is None else item.country_code,
            )
        )
        object.__setattr__(self, "market_contexts", tuple(normalized_contexts))
        if not isinstance(self.nodes, tuple):
            raise TypeError("flow nodes must be an immutable tuple")
        if any(not isinstance(item, FlowNode) for item in self.nodes):
            raise TypeError("flow nodes must contain FlowNode values")
        if not isinstance(self.edges, tuple):
            raise TypeError("flow edges must be an immutable tuple")
        if any(not isinstance(item, FlowEdge) for item in self.edges):
            raise TypeError("flow edges must contain FlowEdge values")

    def canonical_payload(self) -> dict[str, object]:
        """Return a fresh JSON-compatible payload with canonical collection order."""
        contexts = [
            {
                "region": item.region.value,
                "family": item.family.value,
                "venue": item.venue.strip(),
                "country_code": (
                    None if item.country_code is None else item.country_code.strip().upper()
                ),
            }
            for item in self.market_contexts
        ]
        contexts.sort(
            key=lambda item: (
                str(item["region"]),
                str(item["family"]),
                str(item["venue"]),
                "" if item["country_code"] is None else str(item["country_code"]),
            )
        )
        nodes = [
            {
                "node_id": item.node_id,
                "kind": item.kind,
                "parameters": [{"name": name, "value": value} for name, value in item.parameters],
            }
            for item in self.nodes
        ]
        nodes.sort(
            key=lambda item: (
                str(item["node_id"]),
                json.dumps(item, sort_keys=True, separators=(",", ":")),
            )
        )
        edges = [
            {
                "edge_id": item.edge_id,
                "source_node_id": item.source_node_id,
                "source_port": item.source_port,
                "target_node_id": item.target_node_id,
                "target_port": item.target_port,
            }
            for item in self.edges
        ]
        edges.sort(
            key=lambda item: (
                str(item["edge_id"]),
                str(item["source_node_id"]),
                str(item["source_port"]),
                str(item["target_node_id"]),
                str(item["target_port"]),
            )
        )
        return {
            "schema_version": self.schema_version,
            "compiler_contract_version": self.compiler_contract_version,
            "strategy_id": self.strategy_id.value,
            "version": self.version,
            "name": self.name,
            "market_contexts": contexts,
            "nodes": nodes,
            "edges": edges,
        }

    def canonical_json(self) -> str:
        """Serialize every behavior-affecting definition field deterministically."""
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def fingerprint(self) -> str:
        """Return a version-bound SHA-256 fingerprint of the canonical definition."""
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
