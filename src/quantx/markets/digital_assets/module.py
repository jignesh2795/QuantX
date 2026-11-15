"""Global Digital Assets market module.

The module is registration-compatible with ``MarketRegistry`` and represents
the initial Digital Assets spot pack. It does not implement any venue
transport, account, or trading capability.
"""

from __future__ import annotations

from quantx.domain.instruments import MarketRegion
from quantx.markets.common.module_base import MarketModuleBase

from .clock import Continuous24x7Calendar
from .constants import (
    GLOBAL_DIGITAL_ASSETS_MARKET,
    GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
    GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
)


class GlobalDigitalAssetsMarketModule(MarketModuleBase):
    """Market module for the initial Digital Assets spot pack."""


def digital_assets_market_module() -> GlobalDigitalAssetsMarketModule:
    """Create the Global Digital Assets market module."""
    return GlobalDigitalAssetsMarketModule(
        region=MarketRegion.GLOBAL,
        market_contexts=frozenset({GLOBAL_DIGITAL_ASSETS_MARKET}),
        market_pack_id=GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID,
        rule_version=GLOBAL_DIGITAL_ASSETS_RULE_VERSION,
        calendar=Continuous24x7Calendar(),
    )


__all__ = [
    "GlobalDigitalAssetsMarketModule",
    "digital_assets_market_module",
    "GLOBAL_DIGITAL_ASSETS_MARKET",
    "GLOBAL_DIGITAL_ASSETS_MARKET_PACK_ID",
    "GLOBAL_DIGITAL_ASSETS_RULE_VERSION",
]
