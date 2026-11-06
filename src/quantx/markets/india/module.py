"""India market module wrapper.

The registered context set is intentionally limited to the India contexts that
this migration treats as supported module capabilities: NSE equity and NSE
derivatives. Other India venues and families may still be handled by legacy
session, rule, or product-resolution code, but they are not advertised as
supported by ``IndiaMarketModule`` and therefore cannot be selected through
the registry.

The single implemented India market pack currently supplies one pack id and
rule version for every registered context. Product selection remains
NSE-equity-specific; contexts without an explicit compatible product fail
closed during product resolution.
"""

from __future__ import annotations

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.markets.common.module_base import MarketModuleBase
from quantx.markets.india.market_pack import (
    INDIA_EQUITY_MARKET,
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_RULE_VERSION,
)


class IndiaMarketModule(MarketModuleBase):
    """Market module for the implemented India market."""


def india_market_module(session_calendar: object | None = None) -> IndiaMarketModule:
    """Create the India market module without changing India internals."""

    return IndiaMarketModule(
        region=INDIA_EQUITY_MARKET.region,
        market_contexts=frozenset(
            {
                INDIA_EQUITY_MARKET,
                MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN"),
            }
        ),
        market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
        rule_version=INDIA_EQUITY_RULE_VERSION,
        calendar=None,
        session_calendar=session_calendar,
    )


__all__ = ["IndiaMarketModule", "india_market_module"]
