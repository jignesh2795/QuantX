"""Market-specific position margin policy contracts.

QuantX core does not assume a leverage or exchange margin formula. A concrete
adapter supplies the required post-trade margin for an already-accounted
position.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from .accounting import PositionLedgerEntry


class PositionMarginPolicy(Protocol):
    """Calculate explicit margin required for the resulting position."""

    def required_margin(self, position: PositionLedgerEntry) -> Decimal:
        ...


class FixedPerUnitMarginPolicy:
    """Simple deterministic policy useful for paper tests and simulations."""

    def __init__(self, amount_per_unit: Decimal) -> None:
        if amount_per_unit < 0:
            raise ValueError("amount_per_unit cannot be negative")
        self._amount_per_unit = amount_per_unit

    def required_margin(self, position: PositionLedgerEntry) -> Decimal:
        return abs(position.quantity) * self._amount_per_unit
