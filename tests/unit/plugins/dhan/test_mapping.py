from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderType, TimeInForce
from quantx.domain.value_objects import InstrumentId
from quantx.plugins.dhan.mapping import (
    build_order_request,
    dhan_correlation_id,
    dhan_order_type,
    dhan_time_in_force,
    normalize_status,
    parse_dhan_timestamp,
)
from quantx.plugins.dhan.models import DhanInstrumentRef


def _ref() -> DhanInstrumentRef:
    return DhanInstrumentRef(
        security_id="1333",
        exchange_segment="NSE_EQ",
        trading_symbol="TCS",
        product_type="CNC",
    )


def test_dhan_correlation_id_is_deterministic_and_max_30_chars() -> None:
    source = str(uuid4())
    derived = dhan_correlation_id(source)

    assert derived == dhan_correlation_id(source)
    assert len(derived) == 30
    assert derived.isalnum()


def test_order_mapping_matches_dhan_values() -> None:
    assert dhan_order_type(OrderType.MARKET) == "MARKET"
    assert dhan_order_type(OrderType.LIMIT) == "LIMIT"
    assert dhan_order_type(OrderType.STOP) == "STOP_LOSS_MARKET"
    assert dhan_order_type(OrderType.STOP_LIMIT) == "STOP_LOSS"
    assert dhan_time_in_force(TimeInForce.DAY) == "DAY"
    assert dhan_time_in_force(TimeInForce.IOC) == "IOC"


@pytest.mark.parametrize("value", [TimeInForce.GTC, TimeInForce.FOK])
def test_unsupported_dhan_validity_is_rejected(value: TimeInForce) -> None:
    with pytest.raises(ValueError, match="DAY/IOC"):
        dhan_time_in_force(value)


def test_build_order_request_preserves_decimal_order_values() -> None:
    request = build_order_request(
        instrument_ref=_ref(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        limit_price=Decimal("123.45"),
        stop_price=None,
        time_in_force=TimeInForce.DAY,
        correlation_id=str(uuid4()),
    )

    assert request.security_id == "1333"
    assert request.exchange_segment == "NSE_EQ"
    assert request.transaction_type == "BUY"
    assert request.quantity == 2
    assert request.order_type == "LIMIT"
    assert request.product_type == "CNC"
    assert request.price == Decimal("123.45")
    assert request.trigger_price == Decimal("0")
    assert request.validity == "DAY"
    assert len(request.correlation_id) == 30


def test_build_order_request_rejects_fractional_quantity() -> None:
    with pytest.raises(ValueError, match="integral"):
        build_order_request(
            instrument_ref=_ref(),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.5"),
            limit_price=None,
            stop_price=None,
            time_in_force=TimeInForce.DAY,
            correlation_id="abc",
        )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PENDING", "ACCEPTED"),
        ("TRANSIT", "ACCEPTED"),
        ("PART_TRADED", "PARTIALLY_FILLED"),
        ("TRADED", "FILLED"),
        ("REJECTED", "REJECTED"),
        ("CANCELLED", "CANCELLED"),
        ("EXPIRED", "EXPIRED"),
        ("something-new", "UNKNOWN"),
    ],
)
def test_status_mapping(status: str, expected: str) -> None:
    outcome, order_status = normalize_status(status)
    assert outcome == expected
    assert order_status.value == expected


def test_dhan_timestamp_defaults_to_ist_when_timezone_is_omitted() -> None:
    parsed = parse_dhan_timestamp("2026-01-01 10:00:00")

    assert parsed is not None
    assert parsed.utcoffset() == datetime(2026, 1, 1, 10, tzinfo=timezone.utc).utcoffset()
    assert parsed.isoformat().endswith("+05:30")
