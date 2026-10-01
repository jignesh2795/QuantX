"""Position accounting primitives for the market-neutral QuantX core."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .enums import AssetClass
from .instruments import Instrument


@dataclass(frozen=True, slots=True)
class Position:
    """A position in one instrument within one market context."""

    instrument: Instrument
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.average_price < 0:
            raise ValueError("average_price must be non-negative")

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def notional(self) -> Decimal:
        return abs(self.quantity) * self.average_price * self.instrument.multiplier

    @property
    def is_derivative(self) -> bool:
        return self.instrument.asset_class in {
            AssetClass.FUTURE,
            AssetClass.OPTION,
        }
