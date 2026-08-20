"""Explicit mark-to-market valuation for positions and portfolios.

Valuation never fabricates a price. Callers must provide an observable or
explicitly modelled market price for each position being valued.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.positions import Position


class ValuationError(ValueError):
    """Raised when a position cannot be valued from supplied evidence."""


@dataclass(frozen=True, slots=True)
class PositionValuation:
    instrument_id: str
    quantity: Decimal
    mark_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    valuation_source: str


class MarkToMarketValuator:
    """Value positions using explicitly supplied marks."""

    def value_position(
        self,
        position: Position,
        *,
        mark_price: Decimal | None,
        valuation_source: str,
    ) -> PositionValuation:
        if mark_price is None:
            raise ValuationError(f"no mark price available for {position.instrument}")
        if mark_price <= 0:
            raise ValuationError("mark price must be positive")
        if not valuation_source.strip():
            raise ValuationError("valuation_source must not be empty")

        market_value = abs(position.quantity) * mark_price * position.instrument.multiplier
        if position.quantity > 0:
            unrealized = (mark_price - position.average_price) * position.quantity * position.instrument.multiplier
        elif position.quantity < 0:
            unrealized = (position.average_price - mark_price) * abs(position.quantity) * position.instrument.multiplier
        else:
            unrealized = Decimal("0")

        return PositionValuation(
            instrument_id=str(position.instrument),
            quantity=position.quantity,
            mark_price=mark_price,
            market_value=market_value,
            unrealized_pnl=unrealized,
            valuation_source=valuation_source,
        )
