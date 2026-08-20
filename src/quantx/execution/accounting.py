"""Fill-to-position accounting for paper and later live execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide
from quantx.domain.orders import Fill
from quantx.domain.positions import Position
from quantx.domain.value_objects import InstrumentId


@dataclass(frozen=True, slots=True)
class PositionLedgerEntry:
    instrument: InstrumentId
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")


class FillAccounting:
    """Deterministic average-cost accounting for fills.

    The first implementation is deliberately explicit and conservative. More
    market-specific accounting (FIFO, tax lots, derivatives settlement, etc.)
    belongs behind an accounting-policy boundary rather than being embedded in
    execution logic.
    """

    def __init__(self) -> None:
        self._entries: dict[InstrumentId, PositionLedgerEntry] = {}

    def apply(self, fill: Fill, *, fee: Decimal = Decimal("0")) -> PositionLedgerEntry:
        if fee < 0:
            raise ValueError("fee cannot be negative")
        current = self._entries.get(fill.instrument)
        if current is None:
            signed = fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
            entry = PositionLedgerEntry(fill.instrument, signed, fill.price, Decimal("0"), fee)
            self._entries[fill.instrument] = entry
            return entry

        old_qty = current.quantity
        signed_fill = fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
        new_qty = old_qty + signed_fill
        realized = current.realized_pnl

        if old_qty == 0 or (old_qty > 0 and signed_fill > 0) or (old_qty < 0 and signed_fill < 0):
            total_abs = abs(old_qty) + abs(signed_fill)
            avg = ((abs(old_qty) * current.average_price) + (abs(signed_fill) * fill.price)) / total_abs
        elif new_qty == 0:
            avg = Decimal("0")
            realized += (fill.price - current.average_price) * old_qty if old_qty > 0 else (current.average_price - fill.price) * abs(old_qty)
        elif (old_qty > 0 and new_qty > 0) or (old_qty < 0 and new_qty < 0):
            closed = min(abs(old_qty), abs(signed_fill))
            if old_qty > 0:
                realized += (fill.price - current.average_price) * closed
            else:
                realized += (current.average_price - fill.price) * closed
            avg = current.average_price
        else:
            closed = abs(old_qty)
            if old_qty > 0:
                realized += (fill.price - current.average_price) * closed
            else:
                realized += (current.average_price - fill.price) * closed
            avg = fill.price

        entry = PositionLedgerEntry(fill.instrument, new_qty, avg, realized, current.fees + fee)
        self._entries[fill.instrument] = entry
        return entry

    def get(self, instrument: InstrumentId) -> PositionLedgerEntry | None:
        return self._entries.get(instrument)

    def snapshot(self) -> tuple[PositionLedgerEntry, ...]:
        return tuple(self._entries.values())
