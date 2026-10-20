"""Market-neutral instrument and globally separated market primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .enums import AssetClass
from .value_objects import InstrumentId


class MarketRegion(StrEnum):
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


class MarketFamily(StrEnum):
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
    country_code: str | None = None

    def __post_init__(self) -> None:
        if not self.venue.strip():
            raise ValueError("venue must not be empty")
        if self.country_code is not None:
            normalized = self.country_code.strip().upper()
            if len(normalized) != 2:
                raise ValueError("country_code must be a 2-letter code")

    def to_payload(self) -> dict[str, object]:
        """Canonical serializable form of this market classification."""
        return {
            "region": self.region.value,
            "family": self.family.value,
            "venue": self.venue,
            "country_code": self.country_code,
        }

    @classmethod
    def from_payload(cls, payload: object) -> MarketContext:
        """Rebuild a market context, rejecting anything unexpected."""
        if not isinstance(payload, dict):
            raise ValueError("market context must be an object")
        if set(payload) != {"region", "family", "venue", "country_code"}:
            raise ValueError("market context has unexpected fields")
        region = payload["region"]
        family = payload["family"]
        venue = payload["venue"]
        country_code = payload["country_code"]
        if not isinstance(region, str) or not isinstance(family, str):
            raise ValueError("market context region and family must be strings")
        if not isinstance(venue, str):
            raise ValueError("market context venue must be a string")
        if country_code is not None and not isinstance(country_code, str):
            raise ValueError("market context country must be a string or None")
        return cls(
            region=MarketRegion(region),
            family=MarketFamily(family),
            venue=venue,
            country_code=country_code,
        )


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
    underlying: InstrumentId | None = None
    expiry: datetime | None = None
    strike: Decimal | None = None
    option_type: str | None = None

    def __post_init__(self) -> None:
        if self.strike is not None and self.strike <= 0:
            raise ValueError("strike must be positive when supplied")
        if self.option_type is not None:
            normalized = self.option_type.upper()
            if normalized not in {"CALL", "PUT"}:
                raise ValueError("option_type must be CALL or PUT")
