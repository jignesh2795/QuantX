"""Closed v1 Flow node catalogue and statically typed ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .definition import FlowNodeKind, FlowValueType


class FlowParameterType(StrEnum):
    CHOICE = "CHOICE"
    DECIMAL = "DECIMAL"
    CONFIDENCE = "CONFIDENCE"
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    STRING = "STRING"


@dataclass(frozen=True, slots=True)
class FlowParameterSpec:
    name: str
    value_type: FlowParameterType
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Flow parameter name must not be empty")
        if len(self.name) > 64:
            raise ValueError("Flow parameter name must not exceed 64 characters")
        if not isinstance(self.value_type, FlowParameterType):
            raise TypeError("Flow parameter value_type must be a FlowParameterType")
        if not isinstance(self.choices, tuple) or any(
            not isinstance(choice, str) for choice in self.choices
        ):
            raise TypeError("Flow parameter choices must be an immutable tuple of strings")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("Flow parameter choices must be unique")
        if self.value_type is FlowParameterType.CHOICE and not self.choices:
            raise ValueError("CHOICE parameters must declare at least one choice")
        if self.value_type is not FlowParameterType.CHOICE and self.choices:
            raise ValueError("Only CHOICE parameters may declare choices")
        if self.minimum is not None and type(self.minimum) is not int:
            raise TypeError("Flow parameter minimum must be an integer or None")
        if self.maximum is not None and type(self.maximum) is not int:
            raise TypeError("Flow parameter maximum must be an integer or None")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("Flow parameter minimum must not exceed maximum")


@dataclass(frozen=True, slots=True)
class FlowPortSpec:
    name: str
    value_type: str
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Flow port name must not be empty")
        if len(self.name) > 64:
            raise ValueError("Flow port name must not exceed 64 characters")
        valid_types = {
            FlowValueType.DECIMAL,
            FlowValueType.OPTIONAL_DECIMAL,
            FlowValueType.BOOLEAN,
            FlowValueType.OPTIONAL_BOOLEAN,
            FlowValueType.STRING,
            FlowValueType.SIGNAL_ACTION,
            FlowValueType.CONFIDENCE,
            FlowValueType.TRADE_INTENT,
            FlowValueType.STRATEGY_RESULT,
        }
        if not isinstance(self.value_type, str) or self.value_type not in valid_types:
            raise ValueError("Flow port value_type is not a supported FlowValueType")
        if type(self.required) is not bool:
            raise TypeError("Flow port required flag must be a bool")


@dataclass(frozen=True, slots=True)
class FlowNodeSpec:
    kind: str
    parameters: tuple[FlowParameterSpec, ...]
    inputs: tuple[FlowPortSpec, ...]
    outputs: tuple[FlowPortSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("Flow node specification kind must not be empty")
        if len(self.kind) > 64:
            raise ValueError("Flow node specification kind must not exceed 64 characters")
        if not isinstance(self.parameters, tuple):
            raise TypeError("Flow node specification parameters must be an immutable tuple")
        if any(not isinstance(item, FlowParameterSpec) for item in self.parameters):
            raise TypeError("Flow node specification parameters have an invalid item")
        if not isinstance(self.inputs, tuple):
            raise TypeError("Flow node specification inputs must be an immutable tuple")
        if any(not isinstance(item, FlowPortSpec) for item in self.inputs):
            raise TypeError("Flow node specification inputs have an invalid item")
        if not isinstance(self.outputs, tuple):
            raise TypeError("Flow node specification outputs must be an immutable tuple")
        if any(not isinstance(item, FlowPortSpec) for item in self.outputs):
            raise TypeError("Flow node specification outputs have an invalid item")
        for field_name, values in (
            ("parameters", self.parameters),
            ("inputs", self.inputs),
            ("outputs", self.outputs),
        ):
            names = [item.name for item in values]
            if len(names) != len(set(names)):
                raise ValueError(f"Flow node specification {field_name} names must be unique")


def _parameter(
    name: str,
    value_type: FlowParameterType,
    *,
    choices: tuple[str, ...] = (),
    minimum: int | None = None,
    maximum: int | None = None,
) -> FlowParameterSpec:
    return FlowParameterSpec(name, value_type, choices, minimum, maximum)


def _input(name: str, value_type: str, *, required: bool = True) -> FlowPortSpec:
    return FlowPortSpec(name, value_type, required)


def _output(name: str, value_type: str) -> FlowPortSpec:
    return FlowPortSpec(name, value_type)


_specs = {
    FlowNodeKind.EVENT_FIELD: FlowNodeSpec(
        FlowNodeKind.EVENT_FIELD,
        (
            _parameter(
                "field",
                FlowParameterType.CHOICE,
                choices=(
                    "quote.ask",
                    "quote.bid",
                    "quote.last",
                    "quote.mid",
                    "candle.close",
                    "candle.high",
                    "candle.low",
                    "candle.open",
                    "candle.volume",
                ),
            ),
        ),
        (),
        (_output("value", FlowValueType.OPTIONAL_DECIMAL),),
    ),
    FlowNodeKind.PRIOR_CANDLE_FIELD: FlowNodeSpec(
        FlowNodeKind.PRIOR_CANDLE_FIELD,
        (
            _parameter(
                "bars_ago",
                FlowParameterType.INTEGER,
                minimum=1,
                maximum=512,
            ),
            _parameter(
                "field",
                FlowParameterType.CHOICE,
                choices=("close", "high", "low", "open", "volume"),
            ),
        ),
        (),
        (_output("value", FlowValueType.OPTIONAL_DECIMAL),),
    ),
    FlowNodeKind.ENGINE_POSITION_QUANTITY: FlowNodeSpec(
        FlowNodeKind.ENGINE_POSITION_QUANTITY,
        (),
        (),
        (_output("value", FlowValueType.OPTIONAL_DECIMAL),),
    ),
    FlowNodeKind.ENGINE_ACTIVE_ORDER_EXISTS: FlowNodeSpec(
        FlowNodeKind.ENGINE_ACTIVE_ORDER_EXISTS,
        (),
        (),
        (_output("value", FlowValueType.OPTIONAL_BOOLEAN),),
    ),
    FlowNodeKind.DECIMAL_CONSTANT: FlowNodeSpec(
        FlowNodeKind.DECIMAL_CONSTANT,
        (_parameter("value", FlowParameterType.DECIMAL),),
        (),
        (_output("value", FlowValueType.DECIMAL),),
    ),
    FlowNodeKind.CONFIDENCE_CONSTANT: FlowNodeSpec(
        FlowNodeKind.CONFIDENCE_CONSTANT,
        (_parameter("value", FlowParameterType.CONFIDENCE),),
        (),
        (_output("value", FlowValueType.CONFIDENCE),),
    ),
    FlowNodeKind.BOOLEAN_CONSTANT: FlowNodeSpec(
        FlowNodeKind.BOOLEAN_CONSTANT,
        (_parameter("value", FlowParameterType.BOOLEAN),),
        (),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.STRING_CONSTANT: FlowNodeSpec(
        FlowNodeKind.STRING_CONSTANT,
        (_parameter("value", FlowParameterType.STRING),),
        (),
        (_output("value", FlowValueType.STRING),),
    ),
    FlowNodeKind.SIGNAL_ACTION_CONSTANT: FlowNodeSpec(
        FlowNodeKind.SIGNAL_ACTION_CONSTANT,
        (_parameter(
            "value",
            FlowParameterType.CHOICE,
            choices=("BUY", "CLOSE", "HOLD", "SELL"),
        ),),
        (),
        (_output("value", FlowValueType.SIGNAL_ACTION),),
    ),
    FlowNodeKind.DECIMAL_BINARY: FlowNodeSpec(
        FlowNodeKind.DECIMAL_BINARY,
        (_parameter(
            "operator",
            FlowParameterType.CHOICE,
            choices=("ADD", "DIVIDE", "MULTIPLY", "SUBTRACT"),
        ),),
        (
            _input("left", FlowValueType.DECIMAL),
            _input("right", FlowValueType.DECIMAL),
        ),
        (_output("value", FlowValueType.DECIMAL),),
    ),
    FlowNodeKind.DECIMAL_COMPARE: FlowNodeSpec(
        FlowNodeKind.DECIMAL_COMPARE,
        (_parameter(
            "operator",
            FlowParameterType.CHOICE,
            choices=("EQ", "GT", "GTE", "LT", "LTE", "NE"),
        ),),
        (
            _input("left", FlowValueType.DECIMAL),
            _input("right", FlowValueType.DECIMAL),
        ),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.BOOLEAN_BINARY: FlowNodeSpec(
        FlowNodeKind.BOOLEAN_BINARY,
        (_parameter("operator", FlowParameterType.CHOICE, choices=("AND", "OR")),),
        (
            _input("left", FlowValueType.BOOLEAN),
            _input("right", FlowValueType.BOOLEAN),
        ),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.BOOLEAN_NOT: FlowNodeSpec(
        FlowNodeKind.BOOLEAN_NOT,
        (),
        (_input("value", FlowValueType.BOOLEAN),),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.IS_AVAILABLE_DECIMAL: FlowNodeSpec(
        FlowNodeKind.IS_AVAILABLE_DECIMAL,
        (),
        (_input("value", FlowValueType.OPTIONAL_DECIMAL),),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.IS_AVAILABLE_BOOLEAN: FlowNodeSpec(
        FlowNodeKind.IS_AVAILABLE_BOOLEAN,
        (),
        (_input("value", FlowValueType.OPTIONAL_BOOLEAN),),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.REQUIRE_DECIMAL: FlowNodeSpec(
        FlowNodeKind.REQUIRE_DECIMAL,
        (),
        (_input("value", FlowValueType.OPTIONAL_DECIMAL),),
        (_output("value", FlowValueType.DECIMAL),),
    ),
    FlowNodeKind.REQUIRE_BOOLEAN: FlowNodeSpec(
        FlowNodeKind.REQUIRE_BOOLEAN,
        (),
        (_input("value", FlowValueType.OPTIONAL_BOOLEAN),),
        (_output("value", FlowValueType.BOOLEAN),),
    ),
    FlowNodeKind.SELECT_DECIMAL: FlowNodeSpec(
        FlowNodeKind.SELECT_DECIMAL,
        (),
        (
            _input("condition", FlowValueType.BOOLEAN),
            _input("when_false", FlowValueType.DECIMAL),
            _input("when_true", FlowValueType.DECIMAL),
        ),
        (_output("value", FlowValueType.DECIMAL),),
    ),
    FlowNodeKind.ACTION_SELECT: FlowNodeSpec(
        FlowNodeKind.ACTION_SELECT,
        (),
        (
            _input("condition", FlowValueType.BOOLEAN),
            _input("when_false", FlowValueType.SIGNAL_ACTION),
            _input("when_true", FlowValueType.SIGNAL_ACTION),
        ),
        (_output("value", FlowValueType.SIGNAL_ACTION),),
    ),
    FlowNodeKind.TRADE_INTENT: FlowNodeSpec(
        FlowNodeKind.TRADE_INTENT,
        (
            _parameter("order_type", FlowParameterType.CHOICE, choices=("MARKET",)),
            _parameter("side", FlowParameterType.CHOICE, choices=("BUY", "SELL")),
            _parameter("time_in_force", FlowParameterType.CHOICE, choices=("DAY",)),
        ),
        (_input("quantity", FlowValueType.DECIMAL),),
        (_output("intent", FlowValueType.TRADE_INTENT),),
    ),
    FlowNodeKind.STRATEGY_RESULT: FlowNodeSpec(
        FlowNodeKind.STRATEGY_RESULT,
        (),
        (
            _input("action", FlowValueType.SIGNAL_ACTION),
            _input("confidence", FlowValueType.CONFIDENCE),
            _input("intent", FlowValueType.TRADE_INTENT, required=False),
            _input("reason", FlowValueType.STRING),
        ),
        (_output("result", FlowValueType.STRATEGY_RESULT),),
    ),
}

FLOW_NODE_SPECS: Mapping[str, FlowNodeSpec] = MappingProxyType(dict(_specs))
del _specs
FLOW_NODE_KINDS = frozenset(FLOW_NODE_SPECS)
MAX_FLOW_NODES = 256
MAX_FLOW_EDGES = 1024
MAX_FLOW_HISTORY_BARS = 512
