"""Core market-data contracts independent of a broker or UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .value_objects import InstrumentId


class MarketDataType(StrEnum):
    QUOTE = "QUOTE"
    CANDLE = "CANDLE"


@dataclass(frozen=True, slots=True)
class Quote:
    instrument: InstrumentId
    timestamp: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")
        for name in ("bid", "ask", "last", "bid_size", "ask_size"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")


@dataclass(frozen=True, slots=True)
class Candle:
    instrument: InstrumentId
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.timeframe.strip():
            raise ValueError("timeframe must not be empty")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("candle timestamp must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) < 0:
            raise ValueError("candle prices cannot be negative")
        if self.volume < 0:
            raise ValueError("candle volume cannot be negative")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("candle high/low do not contain open/close")


@dataclass(frozen=True, slots=True)
class MarketDataEvent:
    data_type: MarketDataType
    timestamp: datetime
    instrument: InstrumentId
    payload: Quote | Candle

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("market-data event timestamp must be timezone-aware")
        if self.payload.instrument != self.instrument:
            raise ValueError("market-data event instrument must match its payload")
