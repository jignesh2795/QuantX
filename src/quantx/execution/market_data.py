"""Execution-time market data contracts used by paper/live implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantx.domain.value_objects import InstrumentId


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Point-in-time observable market state.

    Missing fields remain None; callers must not invent them.
    """

    instrument: InstrumentId
    timestamp: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        for name in ("bid", "ask", "last", "bid_size", "ask_size"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid
