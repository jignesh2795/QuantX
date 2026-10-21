"""India-specific market metadata kept outside the universal domain core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    DERIVATIVE_ASSET_CLASSES,
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId


class IndianExchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"
    NCDEX = "NCDEX"


class IndianSegment(StrEnum):
    EQUITY = "EQ"
    DERIVATIVES = "FO"
    CURRENCY = "CD"
    COMMODITY = "COM"


class ProductType(StrEnum):
    CNC = "CNC"
    MIS = "MIS"
    NRML = "NRML"
    DELIVERY = "DELIVERY"


@dataclass(frozen=True, slots=True)
class OptionContractSpec:
    underlying: InstrumentId
    expiry: datetime
    strike: Decimal
    option_type: OptionType | str
    lot_size: Decimal

    def __post_init__(self) -> None:
        # A source spelling is normalized exactly once, here at the catalog
        # boundary; downstream code only sees the canonical OptionType.
        if not isinstance(self.option_type, OptionType):
            object.__setattr__(self, "option_type", OptionType.parse(self.option_type))
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


@dataclass(frozen=True, slots=True)
class IndianInstrumentSpec:
    instrument_id: InstrumentId
    symbol: str
    asset_class: AssetClass
    exchange: IndianExchange
    segment: IndianSegment
    currency: str = "INR"
    tick_size: Decimal = Decimal("0.05")
    lot_size: Decimal = Decimal("1")
    multiplier: Decimal = Decimal("1")
    underlying: InstrumentId | None = None
    expiry: datetime | None = None
    strike: Decimal | None = None
    option_type: OptionType | str | None = None

    def __post_init__(self) -> None:
        # The spec is a source boundary: one explicit normalization turns a
        # vendor spelling into the canonical OptionType. An unsupported
        # spelling fails construction closed instead of circulating as a
        # free string.
        if self.option_type is not None and not isinstance(self.option_type, OptionType):
            object.__setattr__(self, "option_type", OptionType.parse(self.option_type))

    def to_instrument(self) -> Instrument:
        if self.asset_class in DERIVATIVE_ASSET_CLASSES:
            family = MarketFamily.DERIVATIVES
        elif self.asset_class is AssetClass.FX:
            family = MarketFamily.FX
        elif self.asset_class is AssetClass.COMMODITY:
            family = MarketFamily.COMMODITIES
        elif self.asset_class is AssetClass.DIGITAL_ASSET:
            family = MarketFamily.DIGITAL_ASSETS
        elif self.asset_class is AssetClass.FUND:
            family = MarketFamily.FUND
        else:
            family = MarketFamily.EQUITY
        market = MarketContext(MarketRegion.INDIA, family, self.exchange.value, "IN")
        return Instrument(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            asset_class=self.asset_class,
            market=market,
            currency=self.currency,
            tick_size=self.tick_size,
            lot_size=self.lot_size,
            multiplier=self.multiplier,
        )

    def to_contract(self) -> Contract | None:
        if self.asset_class not in DERIVATIVE_ASSET_CLASSES:
            return None
        if self.expiry is None:
            raise ValueError("derivative expiry must be supplied")
        if self.expiry.tzinfo is None or self.expiry.utcoffset() is None:
            raise ValueError("derivative expiry must be timezone-aware")

        if self.asset_class is AssetClass.FUTURE:
            if self.strike is not None or self.option_type is not None:
                raise ValueError("futures must not define strike or option_type")
        else:
            if self.strike is None:
                raise ValueError("option strike must be supplied")
            if self.option_type is None:
                raise ValueError("option_type must be supplied")

        if self.underlying is None:
            raise ValueError("derivative underlying must be supplied")

        option_type: OptionType | None = None
        if self.option_type is not None:
            option_type = OptionType.parse(self.option_type)
        return Contract(
            instrument_id=self.instrument_id,
            asset_class=self.asset_class,
            underlying=self.underlying,
            expiry=self.expiry,
            strike=self.strike,
            option_type=option_type,
        )
