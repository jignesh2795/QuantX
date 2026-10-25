from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from quantx.domain.enums import OrderSide, OrderType, TimeInForce
from quantx.domain.value_objects import ProductCode
from quantx.plugins.dhan.mapping import (
    build_order_request,
    dhan_correlation_id,
    dhan_order_type,
    dhan_product_type,
    dhan_time_in_force,
    invert_dhan_product_map,
    normalize_status,
    parse_dhan_timestamp,
    parse_dhan_trade_time,
)
from quantx.plugins.dhan.models import DhanInstrumentRef


def _ref() -> DhanInstrumentRef:
    return DhanInstrumentRef(
        security_id="1333",
        exchange_segment="NSE_EQ",
        trading_symbol="TCS",
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
        product_code=ProductCode("CNC"),
        product_map={"CNC": "CNC"},
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


def test_explicit_product_maps_to_dhan_wire_value() -> None:
    request = build_order_request(
        instrument_ref=_ref(),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        limit_price=None,
        stop_price=None,
        time_in_force=TimeInForce.DAY,
        correlation_id="abc",
        product_code=ProductCode("MIS"),
        product_map={"MIS": "INTRADAY"},
    )

    assert request.product_type == "INTRADAY"
    assert not hasattr(_ref(), "product_type")


def test_distinct_products_for_same_instrument_map_to_distinct_wire_values() -> None:
    product_map = {"CNC": "CNC", "MIS": "INTRADAY"}

    def wire(product: str) -> str:
        return dhan_product_type(ProductCode(product), product_map=product_map)

    assert wire("CNC") == "CNC"
    assert wire("MIS") == "INTRADAY"
    assert wire("CNC") != wire("MIS")


def test_product_mapping_normalizes_case_and_surrounding_space() -> None:
    assert dhan_product_type(ProductCode(" cnc "), product_map={"cnc": " cnc "}) == "CNC"


def test_explicit_product_requires_configured_mapping() -> None:
    with pytest.raises(ValueError, match="no configured Dhan product mapping"):
        dhan_product_type(ProductCode("CNC"))


def test_unsupported_product_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported Dhan product"):
        dhan_product_type(ProductCode("DELIVERY"), product_map={"CNC": "CNC"})


def test_unsupported_mapped_wire_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="configured Dhan product map value is not supported"):
        dhan_product_type(ProductCode("CNC"), product_map={"CNC": "NOT_A_DHAN_PRODUCT"})


def test_absent_product_is_rejected_without_instrument_reference_fallback() -> None:
    with pytest.raises(ValueError, match="resolved approved product"):
        dhan_product_type(None)
    with pytest.raises(ValueError, match="resolved approved product"):
        build_order_request(
            instrument_ref=_ref(),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            limit_price=None,
            stop_price=None,
            time_in_force=TimeInForce.DAY,
            correlation_id="abc",
        )


@pytest.mark.parametrize(
    ("status", "expected_outcome", "expected_status"),
    [
        ("PENDING", "ACCEPTED", "ACCEPTED"),
        ("TRANSIT", "ACCEPTED", "SUBMITTED"),
        ("PART_TRADED", "PARTIALLY_FILLED", "PARTIALLY_FILLED"),
        ("TRADED", "FILLED", "FILLED"),
        ("REJECTED", "REJECTED", "REJECTED"),
        ("CANCELLED", "CANCELLED", "CANCELLED"),
        ("EXPIRED", "EXPIRED", "EXPIRED"),
        ("something-new", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_status_mapping(status: str, expected_outcome: str, expected_status: str) -> None:
    outcome, order_status = normalize_status(status)
    assert outcome == expected_outcome
    assert order_status.value == expected_status


def test_dhan_timestamp_defaults_to_ist_when_timezone_is_omitted() -> None:
    parsed = parse_dhan_timestamp("2026-01-01 10:00:00")

    assert parsed is not None
    assert parsed.utcoffset() == ZoneInfo("Asia/Kolkata").utcoffset(datetime(2026, 1, 1, 10))
    assert parsed.isoformat().endswith("+05:30")


def test_product_mapping_is_adapter_wide_and_makes_no_instrument_specific_claim() -> None:
    """The configured map is the adapter's only product-support authority.

    There is no per-instrument/segment product map, so a rejection must not
    claim instrument-specific validation that the adapter never performed.
    """
    with pytest.raises(ValueError) as excinfo:
        dhan_product_type(ProductCode("DELIVERY"), product_map={"CNC": "CNC"})

    message = str(excinfo.value)
    assert "instrument/segment" not in message
    assert "configured map" in message
    assert dhan_product_type(ProductCode("CNC"), product_map={"CNC": "CNC"}) == "CNC"


def test_position_product_map_inverse_is_explicit_and_deterministic() -> None:
    inverse = invert_dhan_product_map({"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"})

    assert dict(inverse) == {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML"}


def test_position_product_map_rejects_two_neutral_products_on_one_wire_value() -> None:
    with pytest.raises(ValueError, match="ambiguous for wire value"):
        invert_dhan_product_map({"CNC": "CNC", "DELIVERY": "CNC"})


def test_position_product_map_rejects_empty_configuration() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        invert_dhan_product_map({})


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "01/01/1980 00:00:00",
        "1980-01-01T00:00:00",
        "0",
        "0.0",
        0,
        0.0,
        False,
        "not-a-timestamp",
        object(),
        "99999999999999999999",
        "253402300800",
        253402300800,
        "20260101",
        "2026-01-01",
        "0001-01-01T00:00:00",
        1.5,
        -1,
        -1767225600,
    ],
)
def test_unusable_dhan_trade_times_never_become_market_evidence(value: object) -> None:
    assert parse_dhan_trade_time(value) is None


def test_nine_digit_epoch_trade_time_is_supported() -> None:
    parsed = parse_dhan_trade_time(946684800)

    assert parsed is not None
    assert parsed.year == 2000
    assert parsed.isoformat().endswith("+05:30")


def test_integral_float_epoch_trade_time_is_supported() -> None:
    parsed = parse_dhan_trade_time(1767225600.0)

    assert parsed is not None
    assert parsed.year == 2026


def test_iso_dhan_trade_time_defaults_to_ist() -> None:
    parsed = parse_dhan_trade_time("2026-01-01T10:00:00")

    assert parsed is not None
    assert parsed.isoformat().endswith("+05:30")
    assert parsed.hour == 10


def test_epoch_dhan_trade_time_is_interpreted_in_ist() -> None:
    parsed = parse_dhan_trade_time(1767225600)

    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.isoformat().endswith("+05:30")
