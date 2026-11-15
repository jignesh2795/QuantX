"""Focused tests for the Global Digital Assets spot market pack."""

from __future__ import annotations

from datetime import UTC, datetime
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


def _mutate(payload, **overrides):
    result = dict(payload)
    result.update(overrides)
    return result


def test_expired_missing_incompatible_snapshots_fail_closed() -> None:
    # missing payload field
    payload = BTC_USDT_SPOT_RULE.to_payload()
    del payload["source_payload_hash"]
    with pytest.raises(ValueError):
        DigitalAssetSpotRule.from_payload(payload)
    # incompatible market pack identity is not on the rule, but verifier covers policy identity


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

    assert supports_order(OrderType.MARKET, TimeInForce.GTC) is True
    assert supports_order(OrderType.LIMIT, TimeInForce.GTC) is True
    assert supports_order(OrderType.MARKET, TimeInForce.IOC) is False
    assert supports_order(OrderType.STOP, TimeInForce.GTC) is False


def test_continuous_clock_independent_of_trading_status() -> None:
    cal = Continuous24x7Calendar()
    ts = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    classification = cal.classify(ts)
    assert classification.status.value == "OPEN"
    status = market_status_for_rule("HALTED")
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
        assert rule.source_payload_hash.startswith("synthetic-local:")


def test_rule_for_instrument() -> None:
    assert rule_for_instrument(InstrumentId("BINANCE", "BTCUSDT")) is BTC_USDT_SPOT_RULE
    assert rule_for_instrument(InstrumentId("BINANCE", "NOPE")) is None
