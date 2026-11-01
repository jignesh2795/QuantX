"""Base implementation for market modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quantx.domain.instruments import MarketContext, MarketRegion


@dataclass(frozen=True, slots=True)
class MarketModuleBase:
    """Convenience base for market modules.

    Only the core market identity fields are required. Calendar and session
    boundaries are optional seams; their absence means the module does not
    provide that capability.
    """

    region: MarketRegion
    market_contexts: frozenset[MarketContext]
    market_pack_id: str
    rule_version: str
    calendar: Any | None = None
    session_calendar: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region, MarketRegion):
            raise TypeError("region must be a MarketRegion")
        if not isinstance(self.market_contexts, frozenset):
            raise TypeError("market_contexts must be a frozenset")
        if not self.market_contexts:
            raise ValueError("market_contexts must not be empty")
        if any(context.region is not self.region for context in self.market_contexts):
            raise ValueError("every market context must belong to the module region")
        if not isinstance(self.market_pack_id, str) or not self.market_pack_id.strip():
            raise ValueError("market_pack_id must be a non-empty string")
        if not isinstance(self.rule_version, str) or not self.rule_version.strip():
            raise ValueError("rule_version must be a non-empty string")
        if any(not isinstance(context, MarketContext) for context in self.market_contexts):
            raise TypeError("market_contexts must contain MarketContext values")

    # Keep the protocol structural and runtime-checkable-free.
