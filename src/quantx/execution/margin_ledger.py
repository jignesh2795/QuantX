"""Explicit margin reservation state for paper and replay execution.

Margin requirements are supplied by the caller or a market-specific risk
policy. This module does not invent leverage, SPAN, MIS, or broker rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MarginReservation:
    reservation_id: UUID
    amount: Decimal
    released: Decimal = Decimal("0")

    @property
    def outstanding(self) -> Decimal:
        return self.amount - self.released


@dataclass(frozen=True, slots=True)
class MarginState:
    total: Decimal
    used: Decimal
    available: Decimal


class MarginLedger:
    """Stateful reservation/release ledger for one account."""

    def __init__(self, total_margin: Decimal) -> None:
        if total_margin < 0:
            raise ValueError("total margin cannot be negative")
        self._total = total_margin
        self._used = Decimal("0")
        self._reservations: dict[UUID, MarginReservation] = {}

    @property
    def state(self) -> MarginState:
        return MarginState(
            total=self._total,
            used=self._used,
            available=self._total - self._used,
        )

    def reserve(self, reservation_id: UUID, amount: Decimal) -> MarginReservation:
        if amount <= 0:
            raise ValueError("margin reservation must be positive")
        if reservation_id in self._reservations:
            raise ValueError("margin reservation already exists")
        if amount > self.state.available:
            raise ValueError("requested margin exceeds available margin")

        reservation = MarginReservation(reservation_id, amount)
        self._reservations[reservation_id] = reservation
        self._used += amount
        return reservation

    def release(self, reservation_id: UUID, amount: Decimal | None = None) -> MarginReservation:
        current = self._reservations.get(reservation_id)
        if current is None:
            raise KeyError(f"unknown margin reservation: {reservation_id}")

        release_amount = current.outstanding if amount is None else amount
        if release_amount <= 0:
            raise ValueError("margin release must be positive")
        if release_amount > current.outstanding:
            raise ValueError("margin release exceeds outstanding reservation")

        updated = MarginReservation(
            current.reservation_id,
            current.amount,
            current.released + release_amount,
        )
        self._reservations[reservation_id] = updated
        self._used -= release_amount
        return updated

    def reservation(self, reservation_id: UUID) -> MarginReservation | None:
        return self._reservations.get(reservation_id)
