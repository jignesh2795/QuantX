"""Explicit margin reservation state for paper and replay execution.

Margin requirements are supplied by the caller or a market-specific risk
policy. This module does not invent leverage, SPAN, MIS, or broker rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.value_objects import InstrumentId


@dataclass(frozen=True, slots=True)
class MarginReservation:
    reservation_id: UUID
    amount: Decimal
    released: Decimal = Decimal("0")
    instrument: InstrumentId | None = None
    quantity: Decimal | None = None

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

    @property
    def reservations(self) -> tuple[MarginReservation, ...]:
        """Return a read-only snapshot of all margin reservations."""
        return tuple(self._reservations.values())

    def reserve(
        self,
        reservation_id: UUID,
        amount: Decimal,
        *,
        instrument: InstrumentId | None = None,
        quantity: Decimal | None = None,
    ) -> MarginReservation:
        if amount <= 0:
            raise ValueError("margin reservation must be positive")
        if quantity is not None and quantity <= 0:
            raise ValueError("reserved quantity must be positive")
        if reservation_id in self._reservations:
            raise ValueError("margin reservation already exists")
        if amount > self.state.available:
            raise ValueError("requested margin exceeds available margin")

        reservation = MarginReservation(
            reservation_id,
            amount,
            instrument=instrument,
            quantity=quantity,
        )
        self._reservations[reservation_id] = reservation
        self._used += amount
        return reservation

    def release(
        self,
        reservation_id: UUID,
        amount: Decimal | None = None,
    ) -> MarginReservation:
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
            current.instrument,
            current.quantity,
        )
        self._reservations[reservation_id] = updated
        self._used -= release_amount
        return updated

    def set_required_amount(
        self,
        reservation_id: UUID,
        required_amount: Decimal,
    ) -> MarginReservation:
        if required_amount < 0:
            raise ValueError("required margin cannot be negative")
        current = self._reservations.get(reservation_id)
        if current is None:
            raise KeyError(f"unknown margin reservation: {reservation_id}")

        delta = required_amount - current.outstanding
        if delta > 0:
            if delta > self.state.available:
                raise ValueError("required margin exceeds available margin")
            self._used += delta
        elif delta < 0:
            self._used += delta

        updated = MarginReservation(
            current.reservation_id,
            current.amount + max(delta, Decimal("0")),
            current.released + max(-delta, Decimal("0")),
            current.instrument,
            current.quantity,
        )
        self._reservations[reservation_id] = updated
        return updated

    def set_required_amount_for_instrument(
        self,
        instrument: InstrumentId,
        required_amount: Decimal,
    ) -> tuple[MarginReservation, ...]:
        """Resize outstanding reservations for a position as one margin pool.

        A position can be changed by an order whose client ID differs from the
        order that opened it. Position-level margin therefore cannot rely on
        the latest order ID. This method reconciles the total outstanding
        reservation for an instrument to the explicit position requirement,
        preserving individual reservation identities.
        """
        if required_amount < 0:
            raise ValueError("required margin cannot be negative")

        reservations = [
            reservation
            for reservation in self._reservations.values()
            if reservation.instrument == instrument and reservation.outstanding > 0
        ]
        if not reservations:
            if required_amount == 0:
                return ()
            raise KeyError(f"no margin reservation exists for instrument: {instrument}")

        current_total = sum(
            (reservation.outstanding for reservation in reservations),
            Decimal("0"),
        )
        delta = required_amount - current_total

        if delta > 0:
            self.set_required_amount(
                reservations[0].reservation_id,
                reservations[0].outstanding + delta,
            )
        elif delta < 0:
            remaining = -delta
            for reservation in reversed(reservations):
                if remaining == 0:
                    break
                release_amount = min(reservation.outstanding, remaining)
                self.release(reservation.reservation_id, release_amount)
                remaining -= release_amount

        return tuple(self._reservations[reservation.reservation_id] for reservation in reservations)

    def release_for_flat_position(
        self,
        instrument: InstrumentId,
    ) -> tuple[MarginReservation, ...]:
        """Release reservations tied to an instrument after it becomes flat."""
        released: list[MarginReservation] = []
        for reservation_id, reservation in tuple(self._reservations.items()):
            if reservation.instrument != instrument or reservation.outstanding <= 0:
                continue
            released.append(self.release(reservation_id))
        return tuple(released)

    def reservation(self, reservation_id: UUID) -> MarginReservation | None:
        return self._reservations.get(reservation_id)
