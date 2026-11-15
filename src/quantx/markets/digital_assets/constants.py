"""Shared constants for the Global Digital Assets market pack."""

from __future__ import annotations

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion

GLOBAL_DIGITAL_ASSETS_MARKET = MarketContext(
    region=MarketRegion.GLOBAL,
    family=MarketFamily.DIGITAL_ASSETS,
    venue="BINANCE",
    country_code=None,
)

GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID = "global-digital-assets-spot"
GLOBAL_DIGITAL_ASSETS_RULE_VERSION = "digital-assets-spot-fixtures-v1"
