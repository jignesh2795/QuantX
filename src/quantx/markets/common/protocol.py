"""Market module protocol."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.instruments import MarketContext, MarketRegion


class MarketModule(Protocol):
    """Structural contract for one market implementation.

    Required attributes are intentionally small. Optional capabilities are
    supplied through ``MarketModuleBase`` or future, concrete protocols.
    """

    region: MarketRegion
    market_contexts: frozenset[MarketContext]
    market_pack_id: str
    rule_version: str
