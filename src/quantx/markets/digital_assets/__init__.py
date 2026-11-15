"""Synthetic spot pack for Global Digital Assets; no venue execution capability."""

from __future__ import annotations

from .capabilities import (
    DIGITAL_ASSETS_SPOT_CAPABILITIES,
    supports_order,
)
from .clock import (
    Continuous24x7Calendar,
    DigitalAssetMarketStatus,
    DigitalAssetTradingStatus,
    market_status_for_rule,
)
from .constants import (
    GLOBAL_DIGITAL_ASSETS_MARKET,
    GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
)
from .market_pack import (
    DIGITAL_ASSETS_SPOT_PRODUCT,
    GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER,
    GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT,
    GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION,
)
from .module import (
    GlobalDigitalAssetsMarketModule,
    digital_assets_market_module,
)
from .normalization import normalize_symbol, resolve_instrument_id
from .rules import (
    BTC_USDT_SPOT_RULE,
    DIGITAL_ASSET_SPOT_RULES,
    ETH_USDT_SPOT_RULE,
    DigitalAssetSpotRule,
    parse_decimal,
    rule_for_instrument,
    rule_for_symbol,
)

__all__ = [
    "BTC_USDT_SPOT_RULE",
    "Continuous24x7Calendar",
    "DIGITAL_ASSET_SPOT_RULES",
    "DIGITAL_ASSETS_SPOT_CAPABILITIES",
    "DIGITAL_ASSETS_SPOT_PRODUCT",
    "DigitalAssetMarketStatus",
    "DigitalAssetTradingStatus",
    "DigitalAssetSpotRule",
    "ETH_USDT_SPOT_RULE",
    "GLOBAL_DIGITAL_ASSETS_MARKET",
    "GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID",
    "GLOBAL_DIGITAL_ASSETS_POLICY_VERIFIER",
    "GLOBAL_DIGITAL_ASSETS_POSITION_EFFECT",
    "GLOBAL_DIGITAL_ASSETS_PRODUCT_SELECTION",
    "GLOBAL_DIGITAL_ASSETS_RULE_VERSION",
    "GlobalDigitalAssetsMarketModule",
    "digital_assets_market_module",
    "market_status_for_rule",
    "normalize_symbol",
    "parse_decimal",
    "resolve_instrument_id",
    "rule_for_instrument",
    "rule_for_symbol",
    "supports_order",
]
