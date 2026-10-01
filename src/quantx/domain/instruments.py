"""Market-neutral instrument and globally separated market primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from .enums import AssetClass
from .value_objects import InstrumentId


class MarketRegion(str, Enum):
    """Top-level geographic or market jurisdiction classification."""

    INDIA = "INDIA"
    NORTH_AMERICA = "NORTH_AMERICA"
    EUROPE = "EUROPE"
    UK = "UK"
    ASIA_PACIFIC = "ASIA_PACIFIC"
    MIDDLE_EAST = "MIDDLE_EAST"
    AFRICA = "AFRICA"
    LATIN_AMERICA = "LATIN_AMERICA"
    GLOBAL = "GLOBAL"


class MarketFamily(str, Enum):
    """Economic/venue family whose rules may differ materially."""

    EQUITY = "EQUITY"
    DERIVATIVES = "DERIVATIVES"
    FX = "FX"
    COMMODITIES = "COMMODITIES"
    DIGITAL_ASSETS = "DIGITAL_ASSETS"
    FIXED_INCOME = "FIXED_INCOME"
    FUND = "FUND"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Explicit market classification shared by instruments and adapters.

    Market-specific rules belong in market modules/plugins rather than in the
    universal core. The context identifies which rule set should be selected.
    """

    region: MarketRegion
    family: MarketFamily
    venue: str
    country_code: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.venue.strip():
            raise ValueError("venue must not be empty")
        if self.country_code is not None:
            normalized = self.country_code.strip().upper()
            if len(normalized) != 2:
                raise ValueError("country_code must be a 2-letter code")


@dataclass(frozen=True, slots=True)
class Instrument:
    """Tradable instrument identity independent of broker implementation."""

    instrument_id: InstrumentId
    symbol: str
    asset_class: AssetClass
    market: MarketContext
    currency: str
    tick_size: Decimal
    lot_size: Decimal
    multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")


@dataclass(frozen=True, slots=True)
class Contract:
    """Derivative/venue contract metadata layered over an instrument."""

    instrument: Instrument
    underlying: Optional[InstrumentId] = None
    expiry: Optional[datetime] = None
    strike: Optional[Decimal] = None
    option_type: Optional[str] = None

    def __post_init__(self) -> None:
        if self.strike is not None and self.strike <= 0:
            raise ValueError("strike must be positive when supplied")
        if self.option_type is not None:
            normalized = self.option_type.upper()
            if normalized not in {"CALL", "PUT"}:
                raise ValueError("option_type must be CALL or PUT")
