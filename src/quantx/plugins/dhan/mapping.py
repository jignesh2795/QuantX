"""Mappings between QuantX contracts and Dhan API values."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from zoneinfo import ZoneInfo

from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.value_objects import ProductCode

from .models import DhanInstrumentRef, DhanOrderRequest, DhanPayload

_DHAN_ORDER_STATUS: dict[str, tuple[str, OrderStatus]] = {
    "TRANSIT": ("ACCEPTED", OrderStatus.SUBMITTED),
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


def dhan_correlation_id(correlation_id: str) -> str:
    """Derive a deterministic Dhan-safe correlation id from a QuantX id."""
    if not correlation_id.strip():
        raise ValueError("correlation_id must not be empty")
    return hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()[:30]


_SUPPORTED_DHAN_PRODUCTS: set[str] = {"CNC", "INTRADAY", "MARGIN", "MTF"}


def normalize_dhan_product_map(product_map: Mapping[str, str]) -> Mapping[str, str]:
    """Validate and freeze an explicit neutral-to-Dhan product mapping."""
    if not isinstance(product_map, Mapping):
        raise ValueError("Dhan product map must be a mapping")
    if not product_map:
        raise ValueError("Dhan product map must not be empty")

    normalized: dict[str, str] = {}
    for neutral, wire in product_map.items():
        if not isinstance(neutral, str) or not neutral.strip():
            raise ValueError("Dhan product map keys must be non-empty strings")
        if not isinstance(wire, str) or not wire.strip():
            raise ValueError("Dhan product map values must be non-empty strings")
        key = neutral.strip().upper()
        if key in normalized:
            raise ValueError(f"duplicate Dhan product map key: {key}")
        value = wire.strip().upper()
        if value not in _SUPPORTED_DHAN_PRODUCTS:
            raise ValueError(f"configured Dhan product map value is not supported: {value}")
        normalized[key] = value
    return MappingProxyType(normalized)


def invert_dhan_product_map(product_map: Mapping[str, str]) -> Mapping[str, str]:
    """Return the explicit wire-to-neutral inverse of a configured map.

    A wire value produced by two neutral products is ambiguous: the provider
    row cannot be assigned a single canonical product. Such a map is rejected;
    nothing is guessed from the instrument, asset class, or a default.
    """
    normalized = normalize_dhan_product_map(product_map)
    inverse: dict[str, str] = {}
    for neutral, wire in normalized.items():
        if wire in inverse:
            raise ValueError(f"configured Dhan product map is ambiguous for wire value: {wire}")
        inverse[wire] = neutral
    return MappingProxyType(inverse)


def dhan_product_type(
    product_code: ProductCode | None,
    *,
    product_map: Mapping[str, str] | None = None,
) -> str:
    """Translate the already-resolved approved product into a Dhan wire value.

    The mapping is adapter-wide, not instrument-specific: support is decided
    by the configured neutral-to-wire map alone, and no error message claims
    per-instrument or per-segment product support the adapter does not verify.

    There is no instrument-identity fallback: an omitted product is rejected
    here, and the caller must resolve it through a versioned market-pack
    selection policy before submission. Explicit products require a verified
    adapter-supplied mapping; there is no implicit identity mapping from
    neutral codes to Dhan wire codes.
    """
    if product_code is None:
        raise ValueError(
            "Dhan product mapping requires a resolved approved product; "
            "instrument references carry no product default"
        )
    if product_map is None:
        raise ValueError(f"no configured Dhan product mapping for product {product_code.value!r}")
    key = product_code.value.strip().upper()
    normalized_map = normalize_dhan_product_map(product_map)
    mapped = normalized_map.get(key)
    if mapped is None:
        raise ValueError(f"unsupported Dhan product: {key} is absent from the configured map")
    return mapped


def build_order_request(
    *,
    instrument_ref: DhanInstrumentRef,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal,
    limit_price: Decimal | None,
    stop_price: Decimal | None,
    time_in_force: TimeInForce,
    correlation_id: str,
    product_code: ProductCode | None = None,
    product_map: Mapping[str, str] | None = None,
) -> DhanOrderRequest:
    if quantity != quantity.to_integral_value():
        raise ValueError("Dhan regular orders require integral quantities")

    return DhanOrderRequest(
        security_id=instrument_ref.security_id,
        exchange_segment=instrument_ref.exchange_segment,
        transaction_type=dhan_side(side),
        quantity=int(quantity),
        order_type=dhan_order_type(order_type),
        product_type=dhan_product_type(product_code, product_map=product_map),
        price=limit_price if limit_price is not None else Decimal("0"),
        trigger_price=stop_price if stop_price is not None else Decimal("0"),
        validity=dhan_time_in_force(time_in_force),
        correlation_id=dhan_correlation_id(correlation_id),
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
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Dhan decimal field: {key}") from exc
    if not parsed.is_finite():
        raise ValueError(f"invalid Dhan decimal field: {key}")
    return parsed


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


#: Documented Dhan market-quote example that denotes "no trade observed".
#: The documentation does not define a timestamp format for ``last_trade_time``
#: and shows this sentinel value, so only unambiguous ISO/numeric values are
#: interpreted as real trade instants.
_DHAN_SENTINEL_TRADE_TIMES = frozenset(
    {
        "01/01/1980 00:00:00",
        "1980-01-01 00:00:00",
        "1980-01-01t00:00:00",
        "0",
        "0.0",
    }
)

_MIN_TRADE_YEAR = 2000
_MIN_EPOCH_SECONDS_DIGITS = 9
_MAX_EPOCH_SECONDS_DIGITS = 10


def parse_dhan_trade_time(value: object) -> datetime | None:
    """Interpret a Dhan market-quote trade time only when it is unambiguous.

    ``None`` is returned for a missing value, the documented 1980 sentinel, a
    date-only or compact value that could be a date rather than an epoch, an
    out-of-range epoch, a pre-2000 value, or a format the provider
    documentation does not define. Callers must treat ``None`` as unavailable,
    never as "now" and never as fresh evidence.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        normalized = str(value)
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        normalized = str(int(value))
    elif isinstance(value, str):
        normalized = value.strip()
    else:
        return None
    if not normalized or normalized.lower() in _DHAN_SENTINEL_TRADE_TIMES:
        return None
    negative = normalized.startswith("-")
    digits = normalized[1:] if negative else normalized
    if digits.isdigit():
        if negative or not (_MIN_EPOCH_SECONDS_DIGITS <= len(digits) <= _MAX_EPOCH_SECONDS_DIGITS):
            return None
        try:
            parsed = datetime.fromtimestamp(int(digits), tz=ZoneInfo("Asia/Kolkata"))
        except (OverflowError, OSError, ValueError):
            return None
        return parsed if parsed.year >= _MIN_TRADE_YEAR else None
    if "T" not in normalized and " " not in normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return parsed if parsed.year >= _MIN_TRADE_YEAR else None


def extract_filled_quantity(payload: DhanPayload) -> Decimal:
    value = payload.get("filledQty", payload.get("filled_qty", 0))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid Dhan filled quantity") from exc
