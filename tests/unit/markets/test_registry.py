"""MarketRegistry contract tests."""

from __future__ import annotations

import types

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.markets import UnsupportedMarketError, default_market_registry, india_market_module
from quantx.markets.registry import MarketRegistry

INDIA_CONTEXT = next(iter(india_market_module().market_contexts))


def _module(**overrides):
    values = {
        "region": MarketRegion.INDIA,
        "market_contexts": frozenset({INDIA_CONTEXT}),
        "market_pack_id": "pack",
        "rule_version": "version",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def test_register_derives_region_from_module() -> None:
    registry = MarketRegistry()
    module = india_market_module()
    registry.register(module)
    assert registry.get(module.region) is module
    assert INDIA_CONTEXT in module.market_contexts


def test_duplicate_registration_fails_closed() -> None:
    registry = MarketRegistry()
    registry.register(india_market_module())
    with pytest.raises(ValueError):
        registry.register(india_market_module())


def test_missing_required_attributes_fail_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(types.SimpleNamespace(region=MarketRegion.INDIA))


def test_invalid_region_fails_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(region="INDIA"))


def test_non_frozenset_contexts_fail_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(market_contexts={INDIA_CONTEXT}))


def test_empty_context_set_fails_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(market_contexts=frozenset()))


def test_non_context_member_fails_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(market_contexts=frozenset({"not-a-context"})))


def test_context_region_mismatch_fails_closed() -> None:
    registry = MarketRegistry()
    other_context = MarketContext(
        region=MarketRegion.GLOBAL,
        family=MarketFamily.DIGITAL_ASSETS,
        venue="TEST",
    )
    with pytest.raises(ValueError):
        registry.register(_module(market_contexts=frozenset({other_context})))


def test_blank_market_pack_id_fails_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(market_pack_id="   "))


def test_blank_rule_version_fails_closed() -> None:
    registry = MarketRegistry()
    with pytest.raises(ValueError):
        registry.register(_module(rule_version=""))


def test_same_region_unsupported_context_returns_none() -> None:
    registry = MarketRegistry()
    registry.register(india_market_module())
    unsupported = MarketContext(
        region=MarketRegion.INDIA,
        family=INDIA_CONTEXT.family,
        venue="UNREGISTERED",
    )
    assert registry.get_for_context(unsupported) is None


def test_missing_module_returns_none() -> None:
    registry = MarketRegistry()
    assert registry.get(MarketRegion.GLOBAL) is None
    assert (
        registry.get_for_context(
            MarketContext(region=MarketRegion.GLOBAL, family=MarketFamily.DIGITAL_ASSETS, venue="X")
        )
        is None
    )


def test_get_region_cannot_authorize_operation() -> None:
    registry = MarketRegistry()
    registry.register(india_market_module())
    module = registry.get(MarketRegion.INDIA)
    assert module is not None
    unsupported = MarketContext(
        region=MarketRegion.INDIA,
        family=INDIA_CONTEXT.family,
        venue="UNREGISTERED",
    )
    assert registry.get_for_context(unsupported) is None


def test_default_registry_contains_india() -> None:
    registry = default_market_registry()
    assert MarketRegion.INDIA in registry.available()
    assert registry.get_for_context(INDIA_CONTEXT) is not None


def test_digital_assets_placeholder_not_implemented() -> None:
    from quantx.markets.digital_assets import MARKET_IMPLEMENTED, digital_assets_market_module

    assert MARKET_IMPLEMENTED is False
    assert digital_assets_market_module() is None


def test_unsupported_market_error_is_value_error() -> None:
    assert issubclass(UnsupportedMarketError, ValueError)


class StructuralOnlyModule:
    region = MarketRegion.INDIA
    market_contexts = frozenset({INDIA_CONTEXT})
    market_pack_id = "pack"
    rule_version = "version"


def test_structural_only_module_registers_without_market_module_base() -> None:
    registry = MarketRegistry()
    module = StructuralOnlyModule()
    registry.register(module)
    assert registry.get(module.region) is module
    assert registry.get_for_context(INDIA_CONTEXT) is module
