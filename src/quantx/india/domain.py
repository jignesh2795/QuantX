"""India-specific market metadata kept outside the universal domain core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Contract, Instrument, MarketContext, MarketFamily, MarketRegion
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
    option_type: str
    lot_size: Decimal

    def __post_init__(self) -> None:
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if self.option_type.upper() not in {"CALL", "PUT"}:
            raise ValueError("option_type must be CALL or PUT")


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
    expiry: datetime | None = None
    strike: Decimal | None = None
    option_type: str | None = None

    def to_instrument(self) -> Instrument:
        if self.asset_class in {AssetClass.FUTURE, AssetClass.OPTION}:
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
        if self.asset_class not in {AssetClass.FUTURE, AssetClass.OPTION}:
            return None
        return Contract(
            instrument=self.to_instrument(),
            underlying=None,
            expiry=self.expiry,
            strike=self.strike,
            option_type=self.option_type,
        )
