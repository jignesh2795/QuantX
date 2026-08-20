"""Market-neutral instrument and contract domain primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .enums import AssetClass
from .value_objects import InstrumentId


@dataclass(frozen=True, slots=True)
class Instrument:
    """Tradable instrument identity independent of a broker adapter."""

    instrument_id: InstrumentId
    symbol: str
    asset_class: AssetClass
    venue: str
    currency: str
    tick_size: Decimal
    lot_size: Decimal
    multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.venue.strip():
            raise ValueError("venue must not be empty")
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
    """Optional derivative/venue contract metadata layered over an instrument."""

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
