from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from .enums import OrderSide, OrderStatus, OrderType, TimeInForce
from .value_objects import InstrumentId


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        if self.order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and self.stop_price is None:
            raise ValueError("stop_price is required for stop orders")


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
