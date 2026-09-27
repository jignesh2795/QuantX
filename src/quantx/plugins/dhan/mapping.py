"""Mappings between QuantX contracts and Dhan API values."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.value_objects import InstrumentId

from .models import DhanInstrumentRef, DhanOrderRequest, DhanPayload


_DHAN_ORDER_STATUS: dict[str, tuple[str, OrderStatus]] = {
    "TRANSIT": ("ACCEPTED", OrderStatus.ACCEPTED),
    "PENDING": ("ACCEPTED", OrderStatus.ACCEPTED),
    "PART_TRADED": ("PARTIALLY_FILLED", OrderStatus.PARTIALLY_FILLED),
    "TRADED": ("FILLED", OrderStatus.FILLED),
    "REJECTED": ("REJECTED", OrderStatus.REJECTED),
    "CANCELLED": ("CANCELLED", OrderStatus.CANCELLED),
    "EXPIRED": ("EXPIRED", OrderStatus.EXPIRED),
}


def dhan_order_type(order_type: OrderType) -> str:
    if order_type is OrderType.MARKET:
        return "MARKET"
    if order_type is OrderType.LIMIT:
        return "LIMIT"
    if order_type is OrderType.STOP:
        return "STOP_LOSS_MARKET"
    if order_type is OrderType.STOP_LIMIT:
        return "STOP_LOSS"
    raise ValueError(f"unsupported QuantX order type: {order_type}")


def dhan_time_in_force(time_in_force: TimeInForce) -> str:
    if time_in_force in {TimeInForce.DAY, TimeInForce.IOC}:
        return time_in_force.value
    raise ValueError(f"Dhan supports only DAY/IOC validity, got {time_in_force}")


def dhan_side(side: OrderSide) -> str:
    return side.value


def build_order_request(
    *,
    instrument_id: InstrumentId,
    instrument_ref: DhanInstrumentRef,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal,
    limit_price: Decimal | None,
    stop_price: Decimal | None,
    time_in_force: TimeInForce,
    correlation_id: str,
) -> DhanOrderRequest:
    if quantity != quantity.to_integral_value():
        raise ValueError("Dhan regular orders require integral quantities")

    return DhanOrderRequest(
        security_id=instrument_ref.security_id,
        exchange_segment=instrument_ref.exchange_segment,
        transaction_type=dhan_side(side),
        quantity=int(quantity),
        order_type=dhan_order_type(order_type),
        product_type=instrument_ref.product_type,
        price=limit_price if limit_price is not None else Decimal("0"),
        trigger_price=stop_price if stop_price is not None else Decimal("0"),
        validity=dhan_time_in_force(time_in_force),
        correlation_id=correlation_id,
    )


def normalize_status(status: str) -> tuple[str, OrderStatus]:
    normalized = status.strip().upper()
    return _DHAN_ORDER_STATUS.get(
        normalized,
        ("UNKNOWN", OrderStatus.UNKNOWN),
    )


def decimal_field(payload: DhanPayload, key: str) -> Decimal | None:
    value = payload.get(key)
    if value in (None, "", 0, 0.0):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Dhan decimal field: {key}") from exc


def parse_dhan_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"unrecognized Dhan timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return parsed


def extract_filled_quantity(payload: DhanPayload) -> Decimal:
    value = payload.get("filledQty", payload.get("filled_qty", 0))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid Dhan filled quantity") from exc
