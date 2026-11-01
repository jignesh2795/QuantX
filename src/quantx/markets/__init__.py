"""Market-neutral market module contracts and implementations."""

from __future__ import annotations

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.markets.common.calendar import MarketCalendar
from quantx.markets.common.module_base import MarketModuleBase
from quantx.markets.common.protocol import MarketModule
from quantx.markets.registry import MarketRegistry, UnsupportedMarketError

__all__ = [
    "MarketCalendar",
    "MarketContext",
    "MarketFamily",
    "MarketModule",
    "MarketModuleBase",
    "MarketRegion",
    "MarketRegistry",
    "UnsupportedMarketError",
]
