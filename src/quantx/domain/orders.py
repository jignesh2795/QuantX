from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from .enums import OrderSide, OrderStatus, OrderType, PositionEffect, TimeInForce
from .value_objects import InstrumentId, ProductCode


def utc_now() -> datetime:
    """Wall-clock default for interactive/LIVE construction only.

    Replay paths must stamp time explicitly: the deterministic backtest
    restamps orders to the replay occurrence time and the paper venue stamps
    fills from the injected simulation clock. A replay record carrying this
    default is a defect, not a fallback.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Order:
    instrument: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: UUID = field(default_factory=uuid4)
    status: OrderStatus = OrderStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)
    intent_id: UUID | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    required_capabilities: frozenset[str] = frozenset()
    product: ProductCode | None = None
    position_effect: PositionEffect | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        if self.order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and self.stop_price is None:
            raise ValueError("stop_price is required for stop orders")
        if any(not capability.strip() for capability in self.required_capabilities):
            raise ValueError("required capabilities must not contain empty values")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.product is not None and (not str(self.product).strip()):
            raise ValueError("order product must have a non-empty value when specified")
        if self.position_effect is not None and self.position_effect not in {
            PositionEffect.OPEN,
            PositionEffect.CLOSE,
            PositionEffect.AUTO,
        }:
            raise ValueError("position_effect must be OPEN, CLOSE, AUTO, or None")

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
            OrderStatus.UNKNOWN,
        }


@dataclass(frozen=True, slots=True)
class Fill:
    client_order_id: UUID
    instrument: InstrumentId
    side: OrderSide
    quantity: Decimal
    price: Decimal
    filled_at: datetime = field(default_factory=utc_now)
    execution_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if self.price <= 0:
            raise ValueError("fill price must be positive")
        if self.filled_at.tzinfo is None or self.filled_at.utcoffset() is None:
            raise ValueError("filled_at must be timezone-aware")
