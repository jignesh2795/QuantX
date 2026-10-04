"""R1-B3 unit tests: venue-rule product/order compatibility."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
from quantx.domain.orders import Order
from quantx.domain.value_objects import InstrumentId
from quantx.india.domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    ProductType,
)
from quantx.india.execution_rules import IndiaExecutionRuleEngine, IndiaRuleDecision
from quantx.india.rule_data import (
    IndiaRuleScope,
    IndiaVenueRuleSnapshot,
    PriceBandRuleSnapshot,
)

EVALUATED_AT = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
EFFECTIVE_AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


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


def _order(**overrides) -> Order:
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("2"),
    }
    values.update(overrides)
    return Order(**values)


def _band(
    lower: str = "90",
    upper: str = "110",
    *,
    rule_type: str = "OPERATING_RANGE",
) -> PriceBandRuleSnapshot:
    return PriceBandRuleSnapshot(
        lower_bound=Decimal(lower),
        upper_bound=Decimal(upper),
        rule_type=rule_type,
        effective_at=EFFECTIVE_AT,
        source="test-venue",
        version="band-1",
    )


def _rules(**overrides) -> IndiaVenueRuleSnapshot:
    values: dict = {
        "version": "NSE-EQ-2026-01",
        "provenance": "test-venue-rules",
        "effective_at": EFFECTIVE_AT,
        "scope": IndiaRuleScope(
            exchange=IndianExchange.NSE, segment=IndianSegment.EQUITY
        ),
        "allowed_order_types": frozenset(
            {OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT}
        ),
        "allowed_time_in_force": frozenset({TimeInForce.DAY, TimeInForce.IOC}),
        "allowed_products": frozenset({ProductType.CNC, ProductType.MIS}),
        "quantity_freeze": Decimal("10000"),
        "price_band": _band(),
    }
    values.update(overrides)
    return IndiaVenueRuleSnapshot(**values)


def _compat(spec=None, order=None, product=ProductType.CNC, rules=None, **overrides):
    return IndiaExecutionRuleEngine().validate_compatibility(
        spec or _spec(),
        order or _order(),
        product=product,
        venue_rules=rules if rules is not None else _rules(),
        evaluated_at=overrides.pop("evaluated_at", EVALUATED_AT),
    )


def test_valid_compatibility_approves_with_provenance() -> None:
    result = _compat()
    assert result.decision is IndiaRuleDecision.APPROVE
    assert result.rule_set_version == "NSE-EQ-2026-01"
    assert result.provenance == "test-venue-rules"
    assert result.evaluated_at == EVALUATED_AT
    assert result.compatibility_evaluated is True
    assert [check.name for check in result.checks] == [
        "instrument_identity",
        "rule_scope",
        "order_type",
        "order_type_snapshot",
        "time_in_force",
        "quantity",
        "quantity_freeze",
        "price_tick",
        "price_band",
        "derivative_metadata",
        "segment",
        "product",
        "product_snapshot",
    ]


def test_disallowed_order_type_rejected() -> None:
    rules = _rules(allowed_order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}))
    order = _order(order_type=OrderType.STOP, stop_price=Decimal("99.95"))
    result = _compat(order=order, rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_ORDER_TYPE_INVALID" in result.reason


def test_invalid_tif_rejected() -> None:
    order = _order(time_in_force=TimeInForce.GTC)
    result = _compat(order=order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_TIF_INVALID" in result.reason


def test_valid_ioc_tif_approves() -> None:
    order = _order(time_in_force=TimeInForce.IOC)
    assert _compat(order=order).decision is IndiaRuleDecision.APPROVE


def test_quantity_above_freeze_rejected() -> None:
    order = _order(quantity=Decimal("10001"))
    result = _compat(order=order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_QUANTITY_FREEZE_INVALID" in result.reason


def test_quantity_at_freeze_approves() -> None:
    order = _order(quantity=Decimal("10000"))
    assert _compat(order=order).decision is IndiaRuleDecision.APPROVE


def test_tick_aligned_but_outside_band_rejected() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("115.00"))
    result = _compat(order=order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_BAND_INVALID" in result.reason
    assert "INDIA_PRICE_TICK_INVALID" not in result.reason


def test_price_at_band_edge_approves() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("110.00"))
    assert _compat(order=order).decision is IndiaRuleDecision.APPROVE


def test_stop_limit_outside_band_rejected() -> None:
    order = _order(
        order_type=OrderType.STOP_LIMIT,
        limit_price=Decimal("100.05"),
        stop_price=Decimal("85.00"),
    )
    result = _compat(order=order)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRICE_BAND_INVALID" in result.reason


def test_missing_freeze_data_blocks() -> None:
    result = _compat(rules=_rules(quantity_freeze=None))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_missing_band_blocks_price_orders() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
    result = _compat(order=order, rules=_rules(price_band=None))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_missing_order_type_set_blocks() -> None:
    result = _compat(rules=_rules(allowed_order_types=None))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_missing_tif_set_blocks() -> None:
    result = _compat(rules=_rules(allowed_time_in_force=None))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_missing_product_set_blocks() -> None:
    result = _compat(rules=_rules(allowed_products=None))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_future_effective_snapshot_blocks() -> None:
    rules = _rules(effective_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC))
    result = _compat(rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_naive_evaluation_timestamp_blocks() -> None:
    result = _compat(evaluated_at=datetime(2026, 1, 1, 9, 30))
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_incoherent_band_blocks() -> None:
    rules = _rules(price_band=_band(lower="110", upper="90"))
    order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
    result = _compat(order=order, rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason

def test_future_effective_price_band_blocks() -> None:
    future_band = _band()
    future_band = PriceBandRuleSnapshot(
        lower_bound=future_band.lower_bound,
        upper_bound=future_band.upper_bound,
        rule_type=future_band.rule_type,
        effective_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        source=future_band.source,
        version=future_band.version,
    )
    rules = _rules(price_band=future_band)
    order = _order(order_type=OrderType.LIMIT, limit_price=Decimal("100.00"))
    result = _compat(order=order, rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_snapshot_product_refinement_rejects() -> None:
    rules = _rules(allowed_products=frozenset({ProductType.MIS}))
    result = _compat(rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_PRODUCT_INVALID" in result.reason


def test_no_product_skips_product_checks() -> None:
    result = _compat(product=None)
    assert result.decision is IndiaRuleDecision.APPROVE
    assert [check.name for check in result.checks] == [
        "instrument_identity",
        "rule_scope",
        "order_type",
        "order_type_snapshot",
        "time_in_force",
        "quantity",
        "quantity_freeze",
        "price_tick",
        "price_band",
        "derivative_metadata",
        "segment",
    ]


def test_compatibility_is_deterministic() -> None:
    first = _compat()
    second = _compat()
    assert first.decision is second.decision is IndiaRuleDecision.APPROVE
    assert first.reason == second.reason
    assert first.rule_set_version == second.rule_set_version


def test_matching_scope_approves() -> None:
    result = _compat()
    assert result.decision is IndiaRuleDecision.APPROVE
    assert [check.name for check in result.checks][1] == "rule_scope"


def test_instrument_specific_scope_approves() -> None:
    rules = _rules(
        scope=IndiaRuleScope(
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            instrument_id=InstrumentId("NSE", "TCS"),
        )
    )
    assert _compat(rules=rules).decision is IndiaRuleDecision.APPROVE


def test_mismatched_exchange_scope_rejects() -> None:
    rules = _rules(scope=IndiaRuleScope(exchange=IndianExchange.BSE))
    result = _compat(rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_SCOPE_MISMATCH" in result.reason


def test_mismatched_segment_scope_rejects() -> None:
    rules = _rules(scope=IndiaRuleScope(segment=IndianSegment.DERIVATIVES))
    result = _compat(rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_SCOPE_MISMATCH" in result.reason


def test_mismatched_instrument_scope_rejects() -> None:
    rules = _rules(
        scope=IndiaRuleScope(instrument_id=InstrumentId("NSE", "INFY"))
    )
    result = _compat(rules=rules)
    assert result.decision is IndiaRuleDecision.REJECT
    assert "INDIA_RULE_SCOPE_MISMATCH" in result.reason


def test_unknown_scope_fails_closed() -> None:
    for scope in (None, IndiaRuleScope()):
        result = _compat(rules=_rules(scope=scope))
        assert result.decision is IndiaRuleDecision.REJECT
        assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason


def test_snapshot_validation_rejects_blank_identity() -> None:
    with pytest.raises(ValueError, match="version must not be empty"):
        _rules(version="  ")
    with pytest.raises(ValueError, match="provenance must not be empty"):
        _rules(provenance="")
    with pytest.raises(ValueError, match="effective_at must be timezone-aware"):
        _rules(effective_at=datetime(2026, 1, 1, 9, 0))
