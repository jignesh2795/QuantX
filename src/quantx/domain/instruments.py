"""Market-neutral instrument and globally separated market primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .enums import AssetClass
from .value_objects import InstrumentId, canonical_decimal, canonical_instant


class OptionType(StrEnum):
    """The one canonical option-right vocabulary owned by the domain.

    Vendor or source spellings are normalized through :meth:`parse` at the
    explicit catalog/adapter boundary. Core domain objects only carry this
    type, never a free string, so no consumer can invent a competing
    vocabulary.
    """

    CALL = "CALL"
    PUT = "PUT"

    @classmethod
    def parse(cls, value: object) -> OptionType:
        """Normalize one source/vendor spelling at the boundary."""
        if isinstance(value, OptionType):
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("option_type must be CALL or PUT")
        try:
            return cls(value.strip().upper())
        except ValueError as exc:
            raise ValueError("option_type must be CALL or PUT") from exc


#: Asset classes whose canonical metadata includes a derivative contract record.
DERIVATIVE_ASSET_CLASSES: frozenset[AssetClass] = frozenset({AssetClass.FUTURE, AssetClass.OPTION})


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

    def to_payload(self) -> dict[str, object]:
        """Canonical serializable instrument facts, independent of any contract."""
        return {
            "instrument_id": self.instrument_id.to_payload(),
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "market": self.market.to_payload(),
            "currency": self.currency,
            "tick_size": canonical_decimal(self.tick_size),
            "lot_size": canonical_decimal(self.lot_size),
            "multiplier": canonical_decimal(self.multiplier),
        }

    @classmethod
    def from_payload(cls, payload: object) -> Instrument:
        """Rebuild an instrument, rejecting missing or unexpected fields."""
        if not isinstance(payload, dict):
            raise ValueError("instrument must be an object")
        expected = {
            "instrument_id",
            "symbol",
            "asset_class",
            "market",
            "currency",
            "tick_size",
            "lot_size",
            "multiplier",
        }
        if set(payload) != expected:
            raise ValueError("instrument has unexpected fields")
        symbol = payload["symbol"]
        asset_class = payload["asset_class"]
        currency = payload["currency"]
        tick_size = payload["tick_size"]
        lot_size = payload["lot_size"]
        multiplier = payload["multiplier"]
        if not isinstance(symbol, str) or not isinstance(currency, str):
            raise ValueError("instrument symbol and currency must be strings")
        if not isinstance(asset_class, str):
            raise ValueError("instrument asset class must be a string")
        for name, value in (
            ("tick_size", tick_size),
            ("lot_size", lot_size),
            ("multiplier", multiplier),
        ):
            if not isinstance(value, str):
                raise ValueError(f"instrument {name} must be a decimal string")
        return cls(
            instrument_id=InstrumentId.from_payload(payload["instrument_id"]),
            symbol=symbol,
            asset_class=AssetClass(asset_class),
            market=MarketContext.from_payload(payload["market"]),
            currency=currency,
            tick_size=Decimal(tick_size),
            lot_size=Decimal(lot_size),
            multiplier=Decimal(multiplier),
        )


@dataclass(frozen=True, slots=True)
class Contract:
    """Canonical derivative contract metadata keyed by stable instrument identity.

    The contract owns derivative facts only (underlying, expiry, strike, option
    type). It refers to its instrument by ``InstrumentId`` and never embeds a
    second ``Instrument`` copy, so the canonical instrument facts and the
    contract facts cannot contradict each other. Derivative completeness is
    enforced here: an option needs underlying, timezone-aware expiry, a
    positive strike and an ``OptionType``; a future needs underlying and
    timezone-aware expiry and rejects option-only fields. Non-derivative
    instruments have no contract record at all.
    """

    instrument_id: InstrumentId
    asset_class: AssetClass
    underlying: InstrumentId
    expiry: datetime
    strike: Decimal | None = None
    option_type: OptionType | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("contract requires a canonical InstrumentId")
        if not isinstance(self.asset_class, AssetClass):
            raise ValueError("contract requires a canonical AssetClass")
        if self.asset_class not in DERIVATIVE_ASSET_CLASSES:
            raise ValueError("contract metadata requires a derivative asset class")
        if not isinstance(self.underlying, InstrumentId):
            raise ValueError("contract underlying must be an InstrumentId")
        if self.underlying == self.instrument_id:
            raise ValueError("contract underlying must differ from the contract instrument")
        if not isinstance(self.expiry, datetime):
            raise ValueError("contract expiry must be a datetime")
        if self.expiry.tzinfo is None or self.expiry.utcoffset() is None:
            raise ValueError("contract expiry must be timezone-aware")
        if self.option_type is not None and not isinstance(self.option_type, OptionType):
            raise ValueError("option_type must be a canonical OptionType")
        if self.strike is not None and not isinstance(self.strike, Decimal):
            raise ValueError("strike must be a Decimal")

        if self.asset_class is AssetClass.OPTION:
            if self.strike is None:
                raise ValueError("option strike must be supplied")
            if self.option_type is None:
                raise ValueError("option_type must be supplied")
        else:
            if self.strike is not None or self.option_type is not None:
                raise ValueError("futures must not define strike or option_type")
        if self.strike is not None:
            if not self.strike.is_finite() or self.strike <= 0:
                raise ValueError("strike must be positive when supplied")

    def to_payload(self) -> dict[str, object]:
        """Lossless, scale-independent serializable derivative metadata."""
        return {
            "instrument_id": self.instrument_id.to_payload(),
            "asset_class": self.asset_class.value,
            "underlying": self.underlying.to_payload(),
            "expiry": canonical_instant(self.expiry),
            "strike": None if self.strike is None else canonical_decimal(self.strike),
            "option_type": None if self.option_type is None else self.option_type.value,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Contract:
        """Rebuild derivative metadata, rejecting missing or unexpected fields."""
        if not isinstance(payload, dict):
            raise ValueError("contract metadata must be an object")
        expected = {
            "instrument_id",
            "asset_class",
            "underlying",
            "expiry",
            "strike",
            "option_type",
        }
        if set(payload) != expected:
            raise ValueError("contract metadata has unexpected fields")
        asset_class = payload["asset_class"]
        expiry = payload["expiry"]
        strike = payload["strike"]
        option_type = payload["option_type"]
        if not isinstance(asset_class, str):
            raise ValueError("contract asset class must be a string")
        if not isinstance(expiry, str):
            raise ValueError("contract expiry must be a string")
        if strike is not None and not isinstance(strike, str):
            raise ValueError("contract strike must be a decimal string or None")
        if option_type is not None and not isinstance(option_type, str):
            raise ValueError("contract option type must be a string or None")
        return cls(
            instrument_id=InstrumentId.from_payload(payload["instrument_id"]),
            asset_class=AssetClass(asset_class),
            underlying=InstrumentId.from_payload(payload["underlying"]),
            expiry=datetime.fromisoformat(expiry),
            strike=None if strike is None else Decimal(strike),
            option_type=None if option_type is None else OptionType(option_type),
        )
