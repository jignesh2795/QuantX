"""Market module protocol."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.instruments import MarketContext, MarketRegion


class MarketModule(Protocol):
    """Structural contract for one market implementation.

    Required attributes are intentionally small. Optional capabilities are
    supplied through ``MarketModuleBase`` or future, concrete protocols.
    """

    @property
    def region(self) -> MarketRegion: ...

    @property
    def market_contexts(self) -> frozenset[MarketContext]: ...

    @property
    def market_pack_id(self) -> str: ...

    @property
    def rule_version(self) -> str: ...
