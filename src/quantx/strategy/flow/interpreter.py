"""Pure deterministic evaluation of compiled declarative Flow v1 plans.

Decimal arithmetic contract v1:
- precision: 34 significant digits;
- rounding: ROUND_HALF_EVEN;
- exponent range: Emin=-6143, Emax=6144, clamp=0;
- InvalidOperation, DivisionByZero, Overflow, Underflow and FloatOperation trap;
- Inexact/Rounded are permitted and follow the pinned precision/rounding rule.

Every arithmetic operation runs in a fresh local Decimal context. It is independent
of the calling thread's ambient Decimal context. Values remain Decimal throughout
the graph; the only float conversion is the bounded confidence value supplied to
the existing StrategySignal constructor.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import (
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from uuid import NAMESPACE_URL, UUID, uuid5

from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId
from quantx.execution.order_lifecycle import is_terminal_order_status

from ..context import StrategyContext
from ..engine_snapshot import (
    EngineStateSnapshot,
    EvidenceAvailability,
    OpenOrderFact,
    PositionFact,
)
from .catalog import FLOW_NODE_SPECS
from .compiler import FlowCompiler, FlowExecutionPlan, FlowInstruction
from .definition import FLOW_DECIMAL_CONTRACT_VERSION, FlowNode, FlowNodeKind


FLOW_DECIMAL_PRECISION = 34
FLOW_DECIMAL_ROUNDING = ROUND_HALF_EVEN
FLOW_DECIMAL_EMIN = -6143
FLOW_DECIMAL_EMAX = 6144
_FLOW_ID_NAMESPACE: UUID = NAMESPACE_URL


class FlowEvaluationError(ValueError):
    """Stable, location-aware failure raised by Flow v1 evaluation."""

    def __init__(self, code: str, message: str, *, node_id: str | None = None) -> None:
        self.code = code
        self.message = message
        self.node_id = node_id
        location = "" if node_id is None else f" (node={node_id})"
        super().__init__(f"{code}: {message}{location}")


def _new_decimal_context() -> Context:
    context = Context(
        prec=FLOW_DECIMAL_PRECISION,
        rounding=FLOW_DECIMAL_ROUNDING,
        Emin=FLOW_DECIMAL_EMIN,
        Emax=FLOW_DECIMAL_EMAX,
        capitals=1,
        clamp=0,
    )
    for signal in (
        Clamped,
        DivisionByZero,
        FloatOperation,
        Inexact,
        InvalidOperation,
        Overflow,
        Rounded,
        Subnormal,
        Underflow,
    ):
        context.traps[signal] = signal in {
            Clamped,
            DivisionByZero,
            FloatOperation,
            InvalidOperation,
            Overflow,
            Underflow,
        }
    context.clear_flags()
    return context


def _decimal_token(value: Decimal, *, node_id: str | None = None) -> str:
    """Encode a finite Decimal canonically without consulting ambient context."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FlowEvaluationError(
            "invalid_decimal_value",
            "Flow values and evidence must be finite Decimal instances",
            node_id=node_id,
        )
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    normalized = list(digits)
    while normalized and normalized[-1] == 0:
        normalized.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in normalized)
    prefix = "-" if sign else ""
    return f"{prefix}{coefficient}e{exponent}"


def _checked_decimal(value: object, *, node_id: str, source: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FlowEvaluationError(
            "invalid_decimal_evidence",
            f"{source} must be a finite Decimal",
            node_id=node_id,
        )
    return value


def _decimal_operation(operation: str, left: Decimal, right: Decimal, node_id: str) -> Decimal:
    _checked_decimal(left, node_id=node_id, source="left operand")
    _checked_decimal(right, node_id=node_id, source="right operand")
    if operation == "DIVIDE" and right.is_zero():
        raise FlowEvaluationError(
            "division_by_zero",
            "Decimal division by zero is not permitted",
            node_id=node_id,
        )
    try:
        with localcontext(_new_decimal_context()):
            if operation == "ADD":
                result = left + right
            elif operation == "SUBTRACT":
                result = left - right
            elif operation == "MULTIPLY":
                result = left * right
            elif operation == "DIVIDE":
                result = left / right
            else:
                raise FlowEvaluationError(
                    "unsupported_decimal_operator",
                    "Decimal operator is not part of Flow v1",
                    node_id=node_id,
                )
    except DecimalException as exc:
        raise FlowEvaluationError(
            "decimal_arithmetic_error",
            "Decimal operation exceeded the Flow v1 arithmetic contract",
            node_id=node_id,
        ) from exc
    return _checked_decimal(result, node_id=node_id, source="arithmetic result")


def _decimal_compare(operator: str, left: Decimal, right: Decimal, node_id: str) -> bool:
    _checked_decimal(left, node_id=node_id, source="left operand")
    _checked_decimal(right, node_id=node_id, source="right operand")
    if operator == "EQ":
        return left == right
    if operator == "NE":
        return left != right
    if operator == "GT":
        return left > right
    if operator == "GTE":
        return left >= right
    if operator == "LT":
        return left < right
    if operator == "LTE":
        return left <= right
    raise FlowEvaluationError(
        "unsupported_decimal_comparison",
        "Decimal comparison is not part of Flow v1",
        node_id=node_id,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class FlowInterpreter:
    """Evaluate a verified Flow v1 plan against one immutable StrategyContext."""

    def evaluate(self, plan: FlowExecutionPlan, context: StrategyContext) -> StrategyResult:
        if not isinstance(plan, FlowExecutionPlan):
            raise TypeError("plan must be a FlowExecutionPlan")
        if not isinstance(context, StrategyContext):
            raise TypeError("context must be a StrategyContext")

        # Recompile rather than trusting caller-constructed plan objects. This
        # both enforces validation-before-evaluation and detects altered plans.
        expected_plan = FlowCompiler().compile(plan.definition)
        if plan != expected_plan:
            raise FlowEvaluationError(
                "invalid_execution_plan",
                "compiled plan does not match the canonical validated definition",
            )

        definition = plan.definition
        if context.ir.strategy_id != definition.strategy_id:
            raise FlowEvaluationError(
                "strategy_identity_mismatch",
                "Flow strategy identity does not match StrategyContext.ir",
            )
        if context.ir.version != definition.version:
            raise FlowEvaluationError(
                "strategy_version_mismatch",
                "Flow strategy version does not match StrategyContext.ir",
            )
        event = context.event
        if event is None:
            raise FlowEvaluationError(
                "missing_market_event",
                "Flow v1 StrategyResult requires a current market-data event",
            )
        if not isinstance(context.engine, EngineStateSnapshot):
            raise FlowEvaluationError(
                "invalid_engine_snapshot",
                "StrategyContext.engine must be an EngineStateSnapshot",
            )
        self._validate_event(event, context)
        self._validate_history(event.instrument, event.timestamp, context)
        invocation_id = self._invocation_identity(plan, context)

        values: dict[tuple[str, str], object] = {}
        for instruction in plan.instructions:
            inputs = {
                binding.input_port: values[(binding.source_node_id, binding.source_port)]
                for binding in instruction.inputs
                if (binding.source_node_id, binding.source_port) in values
            }
            if len(inputs) != len(instruction.inputs):
                raise FlowEvaluationError(
                    "invalid_execution_plan",
                    "an instruction references an output that has not been evaluated",
                    node_id=instruction.node.node_id,
                )
            output = self._evaluate_node(instruction, inputs, context, invocation_id)
            spec = FLOW_NODE_SPECS[instruction.node.kind]
            if len(spec.outputs) != 1:
                raise FlowEvaluationError(
                    "unsupported_output_shape",
                    "Flow v1 instructions must declare exactly one output",
                    node_id=instruction.node.node_id,
                )
            values[(instruction.node.node_id, spec.outputs[0].name)] = output
            if instruction.node.kind == FlowNodeKind.STRATEGY_RESULT.value:
                if not isinstance(output, StrategyResult):
                    raise FlowEvaluationError(
                        "invalid_strategy_result",
                        "terminal node did not produce a StrategyResult",
                        node_id=instruction.node.node_id,
                    )
                return output

        raise FlowEvaluationError(
            "missing_strategy_result",
            "compiled Flow plan did not produce its terminal StrategyResult",
        )

    @staticmethod
    def _validate_event(event: object, context: StrategyContext) -> None:
        if not isinstance(event, MarketDataEvent):
            raise FlowEvaluationError(
                "invalid_market_event",
                "StrategyContext.event must be a MarketDataEvent",
            )
        if not isinstance(event.data_type, MarketDataType) or not isinstance(
            event.payload, (Quote, Candle)
        ):
            raise FlowEvaluationError(
                "event_payload_type_mismatch",
                "MarketDataEvent must contain a canonical MarketDataType and Quote or Candle payload",
            )
        if event.timestamp.astimezone(UTC) > context.as_of:
            raise FlowEvaluationError(
                "future_market_event",
                "market event is later than the StrategyContext information cut",
            )
        if not isinstance(event.instrument, InstrumentId):
            raise FlowEvaluationError(
                "invalid_event_instrument",
                "market event instrument must be an InstrumentId",
            )
        if event.payload.instrument != event.instrument:
            raise FlowEvaluationError(
                "event_instrument_mismatch",
                "market event and payload instruments must match",
            )
        if event.payload.timestamp.astimezone(UTC) != event.timestamp.astimezone(UTC):
            raise FlowEvaluationError(
                "event_payload_timestamp_mismatch",
                "market event and payload timestamps must identify the same instant",
            )
        if event.data_type is MarketDataType.QUOTE and isinstance(event.payload, Quote):
            for name in ("bid", "ask", "last", "bid_size", "ask_size"):
                value = getattr(event.payload, name)
                if value is not None:
                    _checked_decimal(value, node_id="event", source=f"quote {name}")
            return
        if event.data_type is MarketDataType.CANDLE and isinstance(event.payload, Candle):
            for name in ("open", "high", "low", "close", "volume"):
                _checked_decimal(getattr(event.payload, name), node_id="event", source=f"candle {name}")
            return
        raise FlowEvaluationError(
            "event_payload_type_mismatch",
            "MarketDataEvent data_type must match its canonical Quote or Candle payload",
        )

    @staticmethod
    def _validate_history(instrument: InstrumentId, event_time: datetime, context: StrategyContext) -> None:
        if len(context.history) > 512:
            raise FlowEvaluationError(
                "history_limit_exceeded",
                "StrategyContext history exceeds the Flow v1 maximum of 512 candles",
            )
        if not isinstance(event_time, datetime):
            raise FlowEvaluationError("invalid_event_timestamp", "event timestamp is invalid")
        event_cut = event_time.astimezone(UTC)
        previous: datetime | None = None
        seen: set[datetime] = set()
        for candle in context.history:
            if not isinstance(candle, Candle):
                raise FlowEvaluationError(
                    "invalid_history_item",
                    "StrategyContext history must contain canonical Candle values",
                )
            timestamp = candle.timestamp.astimezone(UTC)
            if candle.instrument != instrument:
                raise FlowEvaluationError(
                    "cross_instrument_history",
                    "prior-candle history must match the current event instrument",
                )
            if timestamp >= event_cut or timestamp >= context.as_of:
                raise FlowEvaluationError(
                    "history_lookahead",
                    "prior-candle history must be strictly earlier than event and context time",
                )
            if timestamp in seen:
                raise FlowEvaluationError(
                    "duplicate_history_timestamp",
                    "prior-candle history timestamps must be unique",
                )
            if previous is not None and timestamp <= previous:
                raise FlowEvaluationError(
                    "history_not_chronological",
                    "prior-candle history must be strictly chronological",
                )
            for name in ("open", "high", "low", "close", "volume"):
                _checked_decimal(
                    getattr(candle, name),
                    node_id="history",
                    source=f"candle {name}",
                )
            seen.add(timestamp)
            previous = timestamp

    @classmethod
    def _invocation_identity(cls, plan: FlowExecutionPlan, context: StrategyContext) -> str:
        event = context.event
        if event is None:
            raise FlowEvaluationError("missing_market_event", "invocation requires a market event")
        payload: dict[str, object]
        if isinstance(event.payload, Quote):
            payload = {
                "kind": "quote",
                "timestamp": event.payload.timestamp.astimezone(UTC).isoformat(
                    timespec="microseconds"
                ),
                "bid": None if event.payload.bid is None else _decimal_token(event.payload.bid),
                "ask": None if event.payload.ask is None else _decimal_token(event.payload.ask),
                "last": None if event.payload.last is None else _decimal_token(event.payload.last),
                "bid_size": (
                    None if event.payload.bid_size is None else _decimal_token(event.payload.bid_size)
                ),
                "ask_size": (
                    None if event.payload.ask_size is None else _decimal_token(event.payload.ask_size)
                ),
            }
        else:
            candle = event.payload
            payload = {
                "kind": "candle",
                "timeframe": candle.timeframe,
                "timestamp": candle.timestamp.astimezone(UTC).isoformat(
                    timespec="microseconds"
                ),
                "open": _decimal_token(candle.open),
                "high": _decimal_token(candle.high),
                "low": _decimal_token(candle.low),
                "close": _decimal_token(candle.close),
                "volume": _decimal_token(candle.volume),
            }

        positions = cls._position_identity(context, event.instrument)
        orders = cls._order_identity(context, event.instrument)
        history = [
            {
                "instrument": candle.instrument.to_payload(),
                "timeframe": candle.timeframe,
                "timestamp": candle.timestamp.astimezone(UTC).isoformat(
                    timespec="microseconds"
                ),
                "open": _decimal_token(candle.open),
                "high": _decimal_token(candle.high),
                "low": _decimal_token(candle.low),
                "close": _decimal_token(candle.close),
                "volume": _decimal_token(candle.volume),
            }
            for candle in context.history
        ]
        identity_payload = {
            "plan": plan.fingerprint,
            "decimal_contract_version": FLOW_DECIMAL_CONTRACT_VERSION,
            "strategy_id": plan.definition.strategy_id.value,
            "strategy_version": plan.definition.version,
            "as_of": context.as_of.isoformat(timespec="microseconds"),
            "event": {
                "data_type": event.data_type.value,
                "timestamp": event.timestamp.astimezone(UTC).isoformat(
                    timespec="microseconds"
                ),
                "instrument": event.instrument.to_payload(),
                "payload": payload,
            },
            "history": history,
            "positions": positions,
            "orders": orders,
        }
        canonical = _canonical_json(identity_payload)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _position_identity(context: StrategyContext, instrument: InstrumentId) -> dict[str, object]:
        collection = context.engine.positions
        if not isinstance(collection.availability, EvidenceAvailability):
            raise FlowEvaluationError("invalid_position_availability", "position availability is invalid")
        items: list[dict[str, object]] = []
        for fact in collection.items:
            if not isinstance(fact, PositionFact):
                raise FlowEvaluationError("invalid_position_fact", "position evidence has an invalid item")
            if fact.instrument != instrument:
                continue
            items.append(
                {
                    "instrument": fact.instrument.to_payload(),
                    "quantity": _decimal_token(fact.quantity),
                    "average_price": _decimal_token(fact.average_price),
                    "realized_pnl": _decimal_token(fact.realized_pnl),
                    "fees": _decimal_token(fact.fees),
                    "effective_at": fact.effective_at.astimezone(UTC).isoformat(
                        timespec="microseconds"
                    ),
                    "evidence_time": (
                        None
                        if fact.evidence_time is None
                        else fact.evidence_time.astimezone(UTC).isoformat(
                            timespec="microseconds"
                        )
                    ),
                }
            )
        items.sort(key=_canonical_json)
        return {
            "availability": collection.availability.value,
            "reason": collection.reason,
            "items": items,
        }

    @staticmethod
    def _order_identity(context: StrategyContext, instrument: InstrumentId) -> dict[str, object]:
        collection = context.engine.orders
        if not isinstance(collection.availability, EvidenceAvailability):
            raise FlowEvaluationError("invalid_order_availability", "order availability is invalid")
        items: list[dict[str, object]] = []
        for fact in collection.items:
            if not isinstance(fact, OpenOrderFact):
                raise FlowEvaluationError("invalid_open_order_fact", "order evidence has an invalid item")
            if fact.instrument != instrument:
                continue
            if not isinstance(fact.status, OrderStatus):
                raise FlowEvaluationError("invalid_order_status", "order evidence status is invalid")
            items.append(
                {
                    "client_order_id": fact.client_order_id,
                    "instrument": fact.instrument.to_payload(),
                    "status": fact.status.value,
                    "order_quantity": _decimal_token(fact.order_quantity),
                    "filled_quantity": (
                        None if fact.filled_quantity is None else _decimal_token(fact.filled_quantity)
                    ),
                    "remaining_quantity": (
                        None
                        if fact.remaining_quantity is None
                        else _decimal_token(fact.remaining_quantity)
                    ),
                    "created_at": fact.created_at.astimezone(UTC).isoformat(
                        timespec="microseconds"
                    ),
                    "evidence_time": (
                        None
                        if fact.evidence_time is None
                        else fact.evidence_time.astimezone(UTC).isoformat(
                            timespec="microseconds"
                        )
                    ),
                    "effective_at": (
                        None
                        if fact.effective_at is None
                        else fact.effective_at.astimezone(UTC).isoformat(
                            timespec="microseconds"
                        )
                    ),
                    "reason": fact.reason,
                }
            )
        items.sort(key=_canonical_json)
        return {
            "availability": collection.availability.value,
            "reason": collection.reason,
            "items": items,
        }

    def _evaluate_node(
        self,
        instruction: FlowInstruction,
        inputs: dict[str, object],
        context: StrategyContext,
        invocation_id: str,
    ) -> object:
        node = instruction.node
        parameters = dict(node.parameters)
        kind = FlowNodeKind(node.kind)
        event = context.event
        if event is None:
            raise FlowEvaluationError("missing_market_event", "node evaluation requires a market event", node_id=node.node_id)

        if kind is FlowNodeKind.EVENT_FIELD:
            return self._event_field(parameters["field"], event.payload, node.node_id)
        if kind is FlowNodeKind.PRIOR_CANDLE_FIELD:
            bars_ago = int(parameters["bars_ago"])
            if len(context.history) < bars_ago:
                return None
            candle = context.history[-bars_ago]
            return _checked_decimal(
                getattr(candle, parameters["field"]),
                node_id=node.node_id,
                source="prior-candle field",
            )
        if kind is FlowNodeKind.ENGINE_POSITION_QUANTITY:
            return self._position_quantity(context, event.instrument, node.node_id)
        if kind is FlowNodeKind.ENGINE_ACTIVE_ORDER_EXISTS:
            return self._active_order_exists(context, event.instrument, node.node_id)
        if kind is FlowNodeKind.DECIMAL_CONSTANT:
            value = Decimal(parameters["value"])
            return _checked_decimal(value, node_id=node.node_id, source="Decimal constant")
        if kind is FlowNodeKind.CONFIDENCE_CONSTANT:
            value = Decimal(parameters["value"])
            if not value.is_finite() or value < 0 or value > 1:
                raise FlowEvaluationError(
                    "invalid_confidence_constant",
                    "confidence must be a finite Decimal between zero and one",
                    node_id=node.node_id,
                )
            return value
        if kind is FlowNodeKind.BOOLEAN_CONSTANT:
            return parameters["value"] == "true"
        if kind is FlowNodeKind.STRING_CONSTANT:
            return parameters["value"]
        if kind is FlowNodeKind.SIGNAL_ACTION_CONSTANT:
            return SignalAction(parameters["value"])
        if kind is FlowNodeKind.DECIMAL_BINARY:
            return _decimal_operation(
                parameters["operator"],
                self._input_decimal(inputs, "left", node.node_id),
                self._input_decimal(inputs, "right", node.node_id),
                node.node_id,
            )
        if kind is FlowNodeKind.DECIMAL_COMPARE:
            return _decimal_compare(
                parameters["operator"],
                self._input_decimal(inputs, "left", node.node_id),
                self._input_decimal(inputs, "right", node.node_id),
                node.node_id,
            )
        if kind is FlowNodeKind.BOOLEAN_BINARY:
            left = self._input_boolean(inputs, "left", node.node_id)
            right = self._input_boolean(inputs, "right", node.node_id)
            return left and right if parameters["operator"] == "AND" else left or right
        if kind is FlowNodeKind.BOOLEAN_NOT:
            return not self._input_boolean(inputs, "value", node.node_id)
        if kind is FlowNodeKind.IS_AVAILABLE_DECIMAL:
            value = inputs["value"]
            if value is not None and not isinstance(value, Decimal):
                raise FlowEvaluationError("invalid_optional_decimal", "optional value is not Decimal", node_id=node.node_id)
            if isinstance(value, Decimal) and not value.is_finite():
                raise FlowEvaluationError("invalid_optional_decimal", "optional Decimal must be finite", node_id=node.node_id)
            return value is not None
        if kind is FlowNodeKind.IS_AVAILABLE_BOOLEAN:
            value = inputs["value"]
            if value is not None and type(value) is not bool:
                raise FlowEvaluationError("invalid_optional_boolean", "optional value is not Boolean", node_id=node.node_id)
            return value is not None
        if kind is FlowNodeKind.REQUIRE_DECIMAL:
            return self._input_decimal(inputs, "value", node.node_id)
        if kind is FlowNodeKind.REQUIRE_BOOLEAN:
            return self._input_boolean(inputs, "value", node.node_id)
        if kind is FlowNodeKind.SELECT_DECIMAL:
            condition = self._input_boolean(inputs, "condition", node.node_id)
            selected = inputs["when_true"] if condition else inputs["when_false"]
            return _checked_decimal(selected, node_id=node.node_id, source="selected Decimal")
        if kind is FlowNodeKind.ACTION_SELECT:
            condition = self._input_boolean(inputs, "condition", node.node_id)
            selected = inputs["when_true"] if condition else inputs["when_false"]
            if not isinstance(selected, SignalAction):
                raise FlowEvaluationError("invalid_selected_action", "selected value is not a SignalAction", node_id=node.node_id)
            return selected
        if kind is FlowNodeKind.TRADE_INTENT:
            quantity = self._input_decimal(inputs, "quantity", node.node_id)
            if quantity <= 0:
                raise FlowEvaluationError(
                    "invalid_intent_quantity",
                    "TradeIntent quantity must be strictly positive",
                    node_id=node.node_id,
                )
            return TradeIntent(
                instrument=event.instrument,
                side=OrderSide(parameters["side"]),
                quantity=quantity,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                strategy_id=context.ir.strategy_id.value,
                strategy_version=context.ir.version,
                intent_id=uuid5(
                    _FLOW_ID_NAMESPACE,
                    f"quantx-flow-v1:{invocation_id}:intent:{node.node_id}",
                ),
            )
        if kind is FlowNodeKind.STRATEGY_RESULT:
            action = inputs["action"]
            if not isinstance(action, SignalAction):
                raise FlowEvaluationError("invalid_result_action", "result action is not a SignalAction", node_id=node.node_id)
            confidence_decimal = self._input_decimal(inputs, "confidence", node.node_id)
            if confidence_decimal < 0 or confidence_decimal > 1:
                raise FlowEvaluationError(
                    "invalid_result_confidence",
                    "result confidence must be between zero and one",
                    node_id=node.node_id,
                )
            reason = inputs["reason"]
            if not isinstance(reason, str):
                raise FlowEvaluationError("invalid_result_reason", "result reason must be a string", node_id=node.node_id)
            intent = inputs.get("intent")
            if intent is not None and not isinstance(intent, TradeIntent):
                raise FlowEvaluationError("invalid_result_intent", "result intent is not a TradeIntent", node_id=node.node_id)
            signal = StrategySignal(
                strategy_id=context.ir.strategy_id,
                strategy_version=context.ir.version,
                instrument=event.instrument,
                action=action,
                confidence=float(confidence_decimal),
                generated_at=event.timestamp,
                reason=reason,
                signal_id=uuid5(
                    _FLOW_ID_NAMESPACE,
                    f"quantx-flow-v1:{invocation_id}:signal:{node.node_id}",
                ),
            )
            return StrategyResult(signal=signal, intent=intent)

        raise FlowEvaluationError(
            "unsupported_node_kind",
            "node kind is not executable by Flow v1",
            node_id=node.node_id,
        )

    @staticmethod
    def _event_field(field: str, payload: Quote | Candle, node_id: str) -> Decimal | None:
        if field.startswith("quote."):
            if not isinstance(payload, Quote):
                return None
            name = field.split(".", maxsplit=1)[1]
            if name == "mid":
                if payload.bid is None or payload.ask is None:
                    return None
                try:
                    with localcontext(_new_decimal_context()):
                        result = (payload.bid + payload.ask) / Decimal("2")
                except DecimalException as exc:
                    raise FlowEvaluationError(
                        "decimal_arithmetic_error",
                        "quote midpoint exceeded the Flow v1 arithmetic contract",
                        node_id=node_id,
                    ) from exc
                return _checked_decimal(result, node_id=node_id, source="quote midpoint")
            value = getattr(payload, name)
            return None if value is None else _checked_decimal(value, node_id=node_id, source=f"quote {name}")
        if field.startswith("candle."):
            if not isinstance(payload, Candle):
                return None
            name = field.split(".", maxsplit=1)[1]
            return _checked_decimal(getattr(payload, name), node_id=node_id, source=f"candle {name}")
        raise FlowEvaluationError("unsupported_event_field", "event field is not part of Flow v1", node_id=node_id)

    @staticmethod
    def _position_quantity(
        context: StrategyContext,
        instrument: InstrumentId,
        node_id: str,
    ) -> Decimal | None:
        collection = context.engine.positions
        if collection.availability is not EvidenceAvailability.AVAILABLE:
            return None
        for fact in collection.items:
            if not isinstance(fact, PositionFact):
                raise FlowEvaluationError(
                    "invalid_position_fact",
                    "position evidence has an invalid item",
                    node_id=node_id,
                )
        matches = tuple(fact for fact in collection.items if fact.instrument == instrument)
        if not matches:
            return Decimal("0")
        if len(matches) != 1:
            raise FlowEvaluationError(
                "ambiguous_position_evidence",
                "complete position evidence contains more than one fact for the current instrument",
                node_id=node_id,
            )
        return _checked_decimal(matches[0].quantity, node_id=node_id, source="position quantity")

    @staticmethod
    def _active_order_exists(
        context: StrategyContext,
        instrument: InstrumentId,
        node_id: str,
    ) -> bool | None:
        collection = context.engine.orders
        for fact in collection.items:
            if not isinstance(fact, OpenOrderFact):
                raise FlowEvaluationError(
                    "invalid_open_order_fact",
                    "active-order evidence has an invalid item",
                    node_id=node_id,
                )
            if fact.instrument != instrument:
                continue
            if not isinstance(fact.status, OrderStatus):
                raise FlowEvaluationError(
                    "invalid_order_status",
                    "active-order evidence has an invalid status",
                    node_id=node_id,
                )
            # A witnessed nonterminal order proves existence, even when the
            # collection is incomplete. Absence proves False only when complete.
            if not is_terminal_order_status(fact.status):
                return True
        if collection.availability is EvidenceAvailability.AVAILABLE:
            return False
        return None

    @staticmethod
    def _input_decimal(inputs: dict[str, object], name: str, node_id: str) -> Decimal:
        value = inputs.get(name)
        if value is None:
            raise FlowEvaluationError(
                "required_decimal_unavailable",
                f"required Decimal input {name!r} is unavailable",
                node_id=node_id,
            )
        return _checked_decimal(value, node_id=node_id, source=f"input {name!r}")

    @staticmethod
    def _input_boolean(inputs: dict[str, object], name: str, node_id: str) -> bool:
        value = inputs.get(name)
        if value is None:
            raise FlowEvaluationError(
                "required_boolean_unavailable",
                f"required Boolean input {name!r} is unavailable",
                node_id=node_id,
            )
        if type(value) is not bool:
            raise FlowEvaluationError(
                "invalid_boolean_input",
                f"input {name!r} must be a Boolean",
                node_id=node_id,
            )
        return value


__all__ = [
    "FLOW_DECIMAL_EMAX",
    "FLOW_DECIMAL_EMIN",
    "FLOW_DECIMAL_PRECISION",
    "FLOW_DECIMAL_ROUNDING",
    "FlowEvaluationError",
    "FlowInterpreter",
]
