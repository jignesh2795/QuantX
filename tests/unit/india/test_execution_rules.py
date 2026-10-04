"""R1-B1 unit tests: deterministic India-market execution rules."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.orders import Order
from quantx.domain.value_objects import InstrumentId
from quantx.india.domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    ProductType,
)
from quantx.india.execution_rules import IndiaExecutionRuleEngine, IndiaRuleDecision

EXPIRY = datetime(2026, 1, 29, 15, 30, tzinfo=UTC)
UNDERLYING = InstrumentId("NSE", "NIFTY")


def _spec(**overrides) -> IndianInstrumentSpec:
    values: dict = {
        "instrument_id": InstrumentId("NSE", "TCS"),
        "symbol": "TCS",
        "asset_class": AssetClass.EQUITY,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.EQUITY,
    }
    values.update(overrides)
    return IndianInstrumentSpec(**values)


def _derivative_spec(asset_class: AssetClass, **overrides) -> IndianInstrumentSpec:
    values: dict = {
        "instrument_id": InstrumentId("NSE", "NIFTY26JANFUT"),
        "symbol": "NIFTY26JANFUT",
        "asset_class": asset_class,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.DERIVATIVES,
        "lot_size": Decimal("25"),
        "underlying": UNDERLYING,
        "expiry": EXPIRY,
    }
    if asset_class is AssetClass.OPTION:
        values.update(
            {
                "instrument_id": InstrumentId("NSE", "NIFTY26JAN100CE"),
                "symbol": "NIFTY26JAN100CE",
                "strike": Decimal("100"),
                "option_type": "CALL",
            }
        )
    values.update(overrides)
    return IndianInstrumentSpec(**values)


def _order(**overrides) -> Order:
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("2"),
    }
    values.update(overrides)
    return Order(**values)


def _validate(spec=None, order=None, product=None):
    return IndiaExecutionRuleEngine().validate(
        spec or _spec(), order or _order(), product=product
    )


def test_valid_single_unit_equity_quantity() -> None:
    result = _validate(_spec(), _order(quantity=Decimal("1")))
    assert result.decision is IndiaRuleDecision.APPROVE


def test_valid_derivative_lot_multiple() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("75")
    )
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_invalid_non_lot_quantity() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("30")
    )
    result = _validate(spec, order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_LOT_SIZE_INVALID" in result.reason


def test_zero_and_negative_quantity_rejected_at_order_boundary() -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        _order(quantity=Decimal("0"))
    with pytest.raises(ValueError, match="quantity must be positive"):
        _order(quantity=Decimal("-1"))


def test_bool_quantity_rejected_by_engine() -> None:
    order = _order(quantity=True)
    result = _validate(_spec(), order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_QUANTITY_INVALID" in result.reason


def test_decimal_exactness_respected() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("75.0")
    )
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE
    fractional = _order(quantity=Decimal("2.5"))
    result = _validate(_spec(), fractional)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_LOT_SIZE_INVALID" in result.reason


def test_invalid_lot_size_spec_fails_closed() -> None:
    for bad_lot in (Decimal("0"), Decimal("-25"), Decimal("NaN")):
        result = _validate(_spec(lot_size=bad_lot), _order())
        assert result.decision is IndiaRuleDecision.REJECT
        assert "INDIA_LOT_SIZE_INVALID" in result.reason


def test_valid_tick_multiples() -> None:
    assert (
        _validate(
            _spec(), _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
        ).decision
        is IndiaRuleDecision.APPROVE
    )
    assert (
        _validate(
            _spec(), _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.05"))
        ).decision
        is IndiaRuleDecision.APPROVE
    )


def test_invalid_tick_multiple() -> None:
    result = _validate(
        _spec(), _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.07"))
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_integer_tick_boundary() -> None:
    spec = _spec(tick_size=Decimal("1"))
    assert (
        _validate(
            spec, _order(order_type=OrderType.LIMIT, limit_price=Decimal("100"))
        ).decision
        is IndiaRuleDecision.APPROVE
    )
    result = _validate(
        spec, _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.5"))
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_stop_price_checked() -> None:
    assert (
        _validate(
            _spec(), _order(order_type=OrderType.STOP, stop_price=Decimal("99.95"))
        ).decision
        is IndiaRuleDecision.APPROVE
    )
    result = _validate(
        _spec(), _order(order_type=OrderType.STOP, stop_price=Decimal("99.93"))
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_stop_limit_checks_both_prices() -> None:
    assert (
        _validate(
            _spec(),
            _order(
                order_type=OrderType.STOP_LIMIT,
                limit_price=Decimal("100.05"),
                stop_price=Decimal("99.95"),
            ),
        ).decision
        is IndiaRuleDecision.APPROVE
    )
    result = _validate(
        _spec(),
        _order(
            order_type=OrderType.STOP_LIMIT,
            limit_price=Decimal("100.05"),
            stop_price=Decimal("99.93"),
        ),
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_market_order_needs_no_price() -> None:
    assert _validate(_spec(), _order(order_type=OrderType.MARKET)).decision is (
        IndiaRuleDecision.APPROVE
    )


def test_bool_price_rejected() -> None:
    result = _validate(
        _spec(), _order(order_type=OrderType.LIMIT, limit_price=True)
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_invalid_tick_size_fails_closed() -> None:
    result = _validate(
        _spec(tick_size=Decimal("0")),
        _order(order_type=OrderType.LIMIT, limit_price=Decimal("100")),
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_TICK_INVALID" in result.reason


def test_valid_future_metadata() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("25")
    )
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_future_missing_expiry_rejected() -> None:
    result = _validate(_derivative_spec(AssetClass.FUTURE, expiry=None), _order())
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_future_missing_underlying_rejected() -> None:
    result = _validate(_derivative_spec(AssetClass.FUTURE, underlying=None), _order())
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_future_with_strike_rejected() -> None:
    result = _validate(
        _derivative_spec(AssetClass.FUTURE, strike=Decimal("100")), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_future_with_option_type_rejected() -> None:
    result = _validate(
        _derivative_spec(AssetClass.FUTURE, option_type="CALL"), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_valid_option_metadata() -> None:
    spec = _derivative_spec(AssetClass.OPTION)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JAN100CE"), quantity=Decimal("25")
    )
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_option_missing_fields_rejected() -> None:
    base = _derivative_spec(AssetClass.OPTION)
    for field in ("expiry", "underlying", "strike"):
        kwargs = {
            "expiry": base.expiry,
            "underlying": base.underlying,
            "strike": base.strike,
            "option_type": base.option_type,
            field: None,
        }
        spec = _derivative_spec(AssetClass.OPTION, **kwargs)
        result = _validate(spec, _order())
        assert result.decision is IndiaRuleDecision.REJECT
        assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_option_invalid_type_rejected() -> None:
    result = _validate(
        _derivative_spec(AssetClass.OPTION, option_type="WEIRD"), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_equity_with_derivative_metadata_rejected() -> None:
    result = _validate(_spec(strike=Decimal("100")), _order())
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_DERIVATIVE_METADATA_INVALID" in result.reason


def test_nse_equity_segment() -> None:
    assert _validate(_spec(), _order()).decision is IndiaRuleDecision.APPROVE


def test_nse_derivatives_segment() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("25")
    )
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_bse_equity_segment() -> None:
    spec = _spec(
        instrument_id=InstrumentId("BSE", "RELIANCE"),
        exchange=IndianExchange.BSE,
        segment=IndianSegment.EQUITY,
    )
    order = _order(instrument=InstrumentId("BSE", "RELIANCE"))
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_mcx_commodity_segment() -> None:
    spec = _spec(
        instrument_id=InstrumentId("MCX", "GOLD"),
        symbol="GOLD",
        asset_class=AssetClass.COMMODITY,
        exchange=IndianExchange.MCX,
        segment=IndianSegment.COMMODITY,
    )
    order = _order(instrument=InstrumentId("MCX", "GOLD"))
    assert _validate(spec, order).decision is IndiaRuleDecision.APPROVE


def test_equity_in_derivatives_segment_rejected() -> None:
    result = _validate(_spec(segment=IndianSegment.DERIVATIVES), _order())
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_SEGMENT_INVALID" in result.reason


def test_commodity_in_equity_segment_rejected() -> None:
    result = _validate(
        _spec(asset_class=AssetClass.COMMODITY, segment=IndianSegment.EQUITY), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_SEGMENT_INVALID" in result.reason


def test_fx_in_commodity_segment_rejected() -> None:
    result = _validate(
        _spec(asset_class=AssetClass.FX, segment=IndianSegment.COMMODITY), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_SEGMENT_INVALID" in result.reason


def test_unknown_asset_segment_fails_closed() -> None:
    result = _validate(
        _spec(asset_class=AssetClass.INDEX, segment=IndianSegment.EQUITY), _order()
    )
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_SEGMENT_INVALID" in result.reason


def test_valid_equity_cnc() -> None:
    assert (
        _validate(_spec(), _order(), product=ProductType.CNC).decision
        is IndiaRuleDecision.APPROVE
    )


def test_valid_equity_mis() -> None:
    assert (
        _validate(_spec(), _order(), product=ProductType.MIS).decision
        is IndiaRuleDecision.APPROVE
    )


def test_derivative_nrml() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("25")
    )
    assert _validate(spec, order, product=ProductType.NRML).decision is (
        IndiaRuleDecision.APPROVE
    )


def test_derivative_mis_permitted() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("25")
    )
    assert _validate(spec, order, product=ProductType.MIS).decision is (
        IndiaRuleDecision.APPROVE
    )


def test_equity_only_product_on_derivative_rejected() -> None:
    spec = _derivative_spec(AssetClass.FUTURE)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("25")
    )
    result = _validate(spec, order, product=ProductType.CNC)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRODUCT_INVALID" in result.reason


def test_delivery_not_accepted_for_derivatives() -> None:
    spec = _derivative_spec(AssetClass.OPTION)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JAN100CE"), quantity=Decimal("25")
    )
    result = _validate(spec, order, product=ProductType.DELIVERY)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRODUCT_INVALID" in result.reason


def test_nrml_not_available_for_equity() -> None:
    result = _validate(_spec(), _order(), product=ProductType.NRML)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRODUCT_INVALID" in result.reason


def test_result_is_deterministic_and_ordered() -> None:
    spec = _derivative_spec(AssetClass.FUTURE, expiry=None)
    order = _order(
        instrument=InstrumentId("NSE", "NIFTY26JANFUT"), quantity=Decimal("30")
    )
    first = _validate(spec, order, product=ProductType.CNC)
    second = _validate(spec, order, product=ProductType.CNC)
    assert first.decision is second.decision is IndiaRuleDecision.REJECT
    assert first.reason == second.reason
    assert [check.name for check in first.checks] == [
        "order_type",
        "quantity",
        "price_tick",
        "derivative_metadata",
        "segment",
        "product",
    ]
