"""Focused tests for the Global Digital Assets spot market pack."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.value_objects import InstrumentId
from quantx.markets.digital_assets import (
    BTC_USDT_SPOT_RULE,
    DIGITAL_ASSET_SPOT_RULES,
    digital_assets_market_module,
)
from quantx.markets.digital_assets.capabilities import supports_order
from quantx.markets.digital_assets.clock import (
    Continuous24x7Calendar,
    DigitalAssetTradingStatus,
    market_status_for_rule,
)
from quantx.markets.digital_assets.constants import (
    GLOBAL_DIGITAL_ASSETS_MARKET,
    GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
)
from quantx.markets.digital_assets.market_pack import (
    DIGITAL_ASSETS_SPOT_PRODUCT,
    GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER,
    GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT,
    GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION,
)
from quantx.markets.digital_assets.normalization import normalize_symbol, resolve_instrument_id
from quantx.markets.digital_assets.rules import (
    DigitalAssetSpotRule,
    parse_decimal,
    rule_for_instrument,
    rule_for_symbol,
)
from quantx.markets.registry import MarketRegistry


def test_exactly_one_global_module_registers() -> None:
    registry = MarketRegistry()
    registry.register(digital_assets_market_module())
    assert MarketRegion.GLOBAL in registry.available()
    with pytest.raises(ValueError):
        registry.register(digital_assets_market_module())


def test_supported_context_resolves() -> None:
    registry = MarketRegistry()
    registry.register(digital_assets_market_module())
    module = registry.get_for_context(GLOBAL_DIGITAL_ASSETS_MARKET)
    assert module is not None
    assert module.market_pack_id == GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID


def test_unsupported_context_fails_closed() -> None:
    registry = MarketRegistry()
    registry.register(digital_assets_market_module())
    unsupported = MarketContext(
        region=MarketRegion.GLOBAL,
        family=MarketFamily.DIGITAL_ASSETS,
        venue="KRAKEN",
    )
    assert registry.get_for_context(unsupported) is None


def test_btc_and_eth_canonical_identities() -> None:
    btc = rule_for_symbol("BTC/USDT")
    eth = rule_for_symbol("ETH/USDT")
    assert btc is not None and eth is not None
    assert btc.instrument_id == InstrumentId("BINANCE", "BTCUSDT")
    assert eth.instrument_id == InstrumentId("BINANCE", "ETHUSDT")
    assert btc.canonical_symbol == "BTC/USDT"
    assert eth.canonical_symbol == "ETH/USDT"
    assert btc.base_asset == "BTC"
    assert btc.quote_asset == "USDT"
    assert eth.base_asset == "ETH"
    assert eth.quote_asset == "USDT"


def test_base_and_quote_distinct_and_usdt_not_usd() -> None:
    for rule in DIGITAL_ASSET_SPOT_RULES:
        assert rule.base_asset != rule.quote_asset
        assert rule.quote_asset == "USDT"
        assert rule.quote_asset != "USD"


def test_decimal_round_trip_exact() -> None:
    payload = BTC_USDT_SPOT_RULE.to_payload()
    rebuilt = DigitalAssetSpotRule.from_payload(payload)
    assert rebuilt == BTC_USDT_SPOT_RULE
    assert rebuilt.price_tick == Decimal("0.01")
    assert rebuilt.quantity_step == Decimal("0.00001")


def test_invalid_constraints_rejected() -> None:
    with pytest.raises(ValueError):
        DigitalAssetSpotRule.from_payload(
            _mutate(BTC_USDT_SPOT_RULE.to_payload(), price_tick="0")
        )
    with pytest.raises(ValueError):
        DigitalAssetSpotRule.from_payload(
            _mutate(BTC_USDT_SPOT_RULE.to_payload(), quantity_min="10", quantity_max="1")
        )
    with pytest.raises(ValueError, match="quantity_min must align"):
        DigitalAssetSpotRule.from_payload(
            _mutate(BTC_USDT_SPOT_RULE.to_payload(), quantity_min="0.000011")
        )


def _mutate(payload, **overrides):
    result = dict(payload)
    result.update(overrides)
    return result


def test_missing_rule_snapshot_field_fails_closed() -> None:
    payload = BTC_USDT_SPOT_RULE.to_payload()
    del payload["source_payload_hash"]
    with pytest.raises(ValueError):
        DigitalAssetSpotRule.from_payload(payload)


def test_rule_effective_and_observation_time_are_evaluated_separately() -> None:
    rule = BTC_USDT_SPOT_RULE
    before_effective = rule.effective_from - timedelta(microseconds=1)
    before_observed = rule.observed_at - timedelta(microseconds=1)

    assert rule.is_effective_at(before_effective) is False
    assert rule.is_effective_at(rule.effective_from) is True
    assert rule.is_observable_at(before_observed) is False
    assert rule.is_observable_at(rule.observed_at) is True
    assert rule.is_valid_at(before_observed) is False
    assert rule.is_valid_at(rule.observed_at) is True
    assert rule.is_effective_at(rule.observed_at + timedelta(days=365)) is True

    assert rule.is_usable_at(
        rule.observed_at,
        market_pack_id=rule.market_pack_id,
        rule_version=rule.rule_version,
    )
    assert not rule.is_usable_at(
        rule.observed_at,
        market_pack_id=rule.market_pack_id,
        rule_version="incompatible-version",
    )


def test_rule_effective_end_is_exclusive() -> None:
    effective_to = datetime(2026, 1, 2, tzinfo=UTC)
    bounded = replace(BTC_USDT_SPOT_RULE, effective_to=effective_to, source_payload_hash="")
    assert bounded.is_effective_at(effective_to - timedelta(microseconds=1))
    assert not bounded.is_effective_at(effective_to)
    assert not bounded.is_valid_at(effective_to)


def test_rule_time_methods_reject_naive_instants() -> None:
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        BTC_USDT_SPOT_RULE.is_effective_at(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        BTC_USDT_SPOT_RULE.is_observable_at(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        BTC_USDT_SPOT_RULE.is_valid_at(naive)


def test_quantity_price_and_reference_notional_validation() -> None:
    rule = BTC_USDT_SPOT_RULE
    assert rule.validate_quantity(Decimal("0.00001")) == Decimal("0.00001")
    assert rule.validate_quantity(Decimal("1.23456")) == Decimal("1.23456")
    with pytest.raises(ValueError, match="outside the rule bounds"):
        rule.validate_quantity(Decimal("0.000001"))
    with pytest.raises(ValueError, match="outside the rule bounds"):
        rule.validate_quantity(Decimal("9000.00001"))
    with pytest.raises(ValueError, match="quantity_step"):
        rule.validate_quantity(Decimal("0.000015"))

    assert rule.validate_limit_price(Decimal("100.01")) == Decimal("100.01")
    with pytest.raises(ValueError, match="price_tick"):
        rule.validate_limit_price(Decimal("100.001"))

    assert rule.validate_reference_notional(Decimal("0.00001"), Decimal("500000")) == Decimal("5.00000")
    with pytest.raises(ValueError, match="below min_notional"):
        rule.validate_reference_notional(Decimal("0.00001"), Decimal("499999"))
    assert rule.validate_reference_notional(Decimal("1"), Decimal("9000000")) == Decimal("9000000")
    with pytest.raises(ValueError, match="exceeds max_notional"):
        rule.validate_reference_notional(Decimal("1"), Decimal("9000000.01"))
    with pytest.raises(ValueError, match="reference_price is required"):
        rule.validate_reference_notional(Decimal("1"), None)
    with pytest.raises(ValueError):
        rule.validate_reference_notional(Decimal("1"), Decimal("0"))


def test_decimal_validation_boundaries_reject_float_and_bool() -> None:
    rule = BTC_USDT_SPOT_RULE
    with pytest.raises(TypeError):
        rule.validate_quantity(1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rule.validate_quantity(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rule.validate_limit_price(1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rule.validate_reference_notional(Decimal("1"), 10.0)  # type: ignore[arg-type]


def test_synthetic_fixture_digest_covers_canonical_rule_payload() -> None:
    for rule in DIGITAL_ASSET_SPOT_RULES:
        digest = rule.source_payload_hash
        assert re.fullmatch(r"synthetic-local:sha256:[0-9a-f]{64}", digest)
        payload = rule.to_payload()
        payload.pop("source_payload_hash")
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert digest == "synthetic-local:sha256:" + hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()


def test_synthetic_digest_changes_when_material_rule_changes() -> None:
    changed = replace(BTC_USDT_SPOT_RULE, price_tick=Decimal("0.02"), source_payload_hash="")
    assert changed.source_payload_hash != BTC_USDT_SPOT_RULE.source_payload_hash

    payload = BTC_USDT_SPOT_RULE.to_payload()
    payload["price_tick"] = "0.02"
    with pytest.raises(ValueError, match="does not match the canonical rule payload"):
        DigitalAssetSpotRule.from_payload(payload)


def test_rule_payload_is_defensively_materialized() -> None:
    payload = BTC_USDT_SPOT_RULE.to_payload()
    payload["supported_time_in_force"].append("IOC")
    payload["instrument_id"]["symbol"] = "CHANGED"
    rebuilt = BTC_USDT_SPOT_RULE.to_payload()
    assert "IOC" not in rebuilt["supported_time_in_force"]
    assert rebuilt["instrument_id"]["symbol"] == "BTCUSDT"


def test_unknown_trading_status_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported digital-asset trading status"):
        replace(BTC_USDT_SPOT_RULE, trading_status="UNKNOWN_STATUS", source_payload_hash="")
    with pytest.raises(ValueError, match="unsupported digital-asset trading status"):
        market_status_for_rule("UNKNOWN_STATUS")


def test_floats_and_bools_rejected() -> None:
    with pytest.raises(TypeError):
        parse_decimal(True, "x")
    with pytest.raises(TypeError):
        parse_decimal(1.5, "x")


def test_spot_product_selection_verifier() -> None:
    from quantx.domain.product_selection import ProductSelectionResolution

    resolution = ProductSelectionResolution(
        market=GLOBAL_DIGITAL_ASSETS_MARKET,
        product=DIGITAL_ASSETS_SPOT_PRODUCT,
        market_pack_id=GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
        rule_version=GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
    )
    GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION.verify_resolution(resolution)
    GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER.verify_product_resolution(
        resolution, execution_context=_ctx()
    )


def _ctx():
    from quantx.domain.deployment import ExecutionContext, ExecutionMode

    return ExecutionContext(
        account_id="acct",
        portfolio_id="pf",
        deployment_id="dep",
        market=GLOBAL_DIGITAL_ASSETS_MARKET,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id=GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
        rule_version=GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
    )


def test_spot_position_effect_not_applicable() -> None:
    from quantx.domain.position_effect import (
        resolve_absent_position_effect,
    )

    resolution, bound = resolve_absent_position_effect(
        _ctx(),
        product=DIGITAL_ASSETS_SPOT_PRODUCT,
        policy=GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT,
    )
    assert resolution.policy_resolution is not None
    assert resolution.policy_resolution.not_applicable is True
    assert resolution.effective is None
    GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER.verify_absent_effect_resolution(
        resolution.policy_resolution, execution_context=bound, product=DIGITAL_ASSETS_SPOT_PRODUCT
    )


def test_order_tif_capability_matrix() -> None:
    from quantx.domain.enums import OrderType, TimeInForce

    assert supports_order(OrderType.MARKET, None) is True
    assert supports_order(OrderType.LIMIT, TimeInForce.GTC) is True
    assert supports_order(OrderType.MARKET, TimeInForce.GTC) is False
    assert supports_order(OrderType.MARKET, TimeInForce.DAY) is False
    assert supports_order(OrderType.MARKET, TimeInForce.IOC) is False
    assert supports_order(OrderType.MARKET, TimeInForce.FOK) is False
    assert supports_order(OrderType.LIMIT, None) is False
    assert supports_order(OrderType.LIMIT, TimeInForce.DAY) is False
    assert supports_order(OrderType.LIMIT, TimeInForce.IOC) is False
    assert supports_order(OrderType.LIMIT, TimeInForce.FOK) is False
    assert supports_order(OrderType.STOP, TimeInForce.GTC) is False

    assert BTC_USDT_SPOT_RULE.supports(OrderType.MARKET, None) is True
    assert BTC_USDT_SPOT_RULE.supports(OrderType.MARKET, TimeInForce.GTC) is False
    assert BTC_USDT_SPOT_RULE.supports(OrderType.LIMIT, TimeInForce.GTC) is True


def test_continuous_clock_independent_of_trading_status() -> None:
    cal = Continuous24x7Calendar()
    ts = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    classification = cal.classify(ts)
    assert classification.status.value == "OPEN"
    status = market_status_for_rule(DigitalAssetTradingStatus.HALTED)
    assert status.market_clock_open is True
    assert status.instrument_trading_enabled is False
    assert status.can_trade is False


def test_symbol_normalization_deterministic() -> None:
    assert normalize_symbol("btcusdt") == "BTC/USDT"
    assert normalize_symbol("BTC/USDT") == "BTC/USDT"
    assert normalize_symbol("ETH-USDT") == "ETH/USDT"
    assert resolve_instrument_id("btcusdt") == InstrumentId("BINANCE", "BTCUSDT")
    with pytest.raises(ValueError):
        normalize_symbol("BTC/XXX")
    with pytest.raises(ValueError):
        normalize_symbol("")


def test_synthetic_provenance_present() -> None:
    for rule in DIGITAL_ASSET_SPOT_RULES:
        assert rule.synthetic is True
        assert "synthetic" in rule.rule_source.lower()
        assert re.fullmatch(r"synthetic-local:sha256:[0-9a-f]{64}", rule.source_payload_hash)


def test_rule_for_instrument() -> None:
    assert rule_for_instrument(InstrumentId("BINANCE", "BTCUSDT")) is BTC_USDT_SPOT_RULE
    assert rule_for_instrument(InstrumentId("BINANCE", "NOPE")) is None
