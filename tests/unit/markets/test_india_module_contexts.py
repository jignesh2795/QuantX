from __future__ import annotations

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.markets import india_market_module
from quantx.markets.registry import MarketRegistry


def test_india_market_module_registers_exact_supported_contexts() -> None:
    module = india_market_module()

    assert module.market_contexts == frozenset(
        {
            MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
            MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN"),
        }
    )


def test_unregistered_india_context_is_not_selectable() -> None:
    registry = MarketRegistry()
    registry.register(india_market_module())

    unsupported = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")

    assert registry.get_for_context(unsupported) is None


def test_registered_contexts_share_one_pack_identity() -> None:
    module = india_market_module()

    assert module.market_pack_id == "india-equity"
    assert module.rule_version == "india-products-v1"
    for context in module.market_contexts:
        assert context.region is module.region
