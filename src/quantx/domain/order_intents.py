"""Strategy-level trade intent primitives.

TradeIntent represents what a strategy requests. It is deliberately distinct
from Order, which represents an execution-approved instruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from .deployment import ExecutionContext
from .enums import OrderSide, OrderType, TimeInForce
from .value_objects import InstrumentId


@dataclass(frozen=True, slots=True)
class TradeIntent:
    instrument: InstrumentId
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    required_margin: Decimal = Decimal("0")
    estimated_order_value: Decimal | None = None
    required_capabilities: frozenset[str] = frozenset()
    approval_required: bool = False
    execution_context: ExecutionContext | None = None
    intent_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("intent quantity must be positive")
        if self.required_margin < 0:
            raise ValueError("required_margin cannot be negative")
        if self.estimated_order_value is not None and self.estimated_order_value < 0:
            raise ValueError("estimated_order_value cannot be negative")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit_price is required for limit intents")
        if self.order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and self.stop_price is None:
            raise ValueError("stop_price is required for stop intents")
