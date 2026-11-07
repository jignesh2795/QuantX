"""Declarative Flow v1 contracts, validation, compilation and pure interpretation."""

from .catalog import (
    FLOW_NODE_KINDS,
    FLOW_NODE_SPECS,
    MAX_FLOW_EDGES,
    MAX_FLOW_HISTORY_BARS,
    MAX_FLOW_NODES,
    FlowNodeSpec,
    FlowParameterSpec,
    FlowParameterType,
    FlowPortSpec,
)
from .compiler import FlowCompiler, FlowExecutionPlan, FlowInputBinding, FlowInstruction
from .definition import (
    FLOW_COMPILER_CONTRACT_VERSION,
    FLOW_DECIMAL_CONTRACT_VERSION,
    FLOW_SCHEMA_VERSION,
    MAX_FLOW_PARAMETER_LENGTH,
    FlowDefinition,
    FlowEdge,
    FlowNode,
    FlowNodeKind,
    FlowValueType,
)
from .interpreter import (
    FLOW_DECIMAL_EMAX,
    FLOW_DECIMAL_EMIN,
    FLOW_DECIMAL_PRECISION,
    FLOW_DECIMAL_ROUNDING,
    FlowEvaluationError,
    FlowInterpreter,
)
from .runtime_adapter import FlowExecutableStrategy
from .validation import (
    FlowDefinitionValidationError,
    FlowDefinitionValidator,
    FlowValidationIssue,
    FlowValidationResult,
)

__all__ = [
    "FLOW_COMPILER_CONTRACT_VERSION",
    "FLOW_DECIMAL_CONTRACT_VERSION",
    "FLOW_DECIMAL_EMAX",
    "FLOW_DECIMAL_EMIN",
    "FLOW_DECIMAL_PRECISION",
    "FLOW_DECIMAL_ROUNDING",
    "FLOW_NODE_KINDS",
    "FLOW_NODE_SPECS",
    "FLOW_SCHEMA_VERSION",
    "MAX_FLOW_EDGES",
    "MAX_FLOW_HISTORY_BARS",
    "MAX_FLOW_NODES",
    "MAX_FLOW_PARAMETER_LENGTH",
    "FlowCompiler",
    "FlowDefinition",
    "FlowDefinitionValidationError",
    "FlowDefinitionValidator",
    "FlowEdge",
    "FlowEvaluationError",
    "FlowExecutionPlan",
    "FlowExecutableStrategy",
    "FlowInputBinding",
    "FlowInstruction",
    "FlowInterpreter",
    "FlowNode",
    "FlowNodeKind",
    "FlowNodeSpec",
    "FlowParameterSpec",
    "FlowParameterType",
    "FlowPortSpec",
    "FlowValidationIssue",
    "FlowValidationResult",
    "FlowValueType",
]
