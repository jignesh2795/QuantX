"""Immutable strategy-facing projections of canonical engine evidence.

This module owns read views only. It does not perform accounting, lifecycle
reduction, valuation, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import OrderStatus
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.execution.accounting import PositionLedgerEntry
from quantx.execution.historical_account_state import (
    AccountStateCompleteness,
    HistoricalAccountStateSnapshot,
)
from quantx.execution.order_lifecycle import is_terminal_order_status


class EvidenceAvailability(StrEnum):
    """Whether a snapshot dimension is authoritative and complete."""

    AVAILABLE = "AVAILABLE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class EvidenceCollection[T]:
    """An immutable evidence set with explicit empty-versus-unknown semantics."""

    items: tuple[T, ...]
    availability: EvidenceAvailability
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("evidence items must be a tuple")
        if self.availability is EvidenceAvailability.AVAILABLE and self.reason is not None:
            raise ValueError("available evidence cannot carry an unavailable reason")
        if self.availability is not EvidenceAvailability.AVAILABLE and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("incomplete or unavailable evidence requires a reason")
        if self.availability is EvidenceAvailability.UNAVAILABLE and self.items:
            raise ValueError("unavailable evidence cannot expose items")

    @classmethod
    def known(cls, items: tuple[T, ...]) -> EvidenceCollection[T]:
        return cls(items=items, availability=EvidenceAvailability.AVAILABLE)

    @classmethod
    def incomplete(
        cls, items: tuple[T, ...], reason: str
    ) -> EvidenceCollection[T]:
        return cls(items=items, availability=EvidenceAvailability.INCOMPLETE, reason=reason)

    @classmethod
    def unavailable(cls, reason: str) -> EvidenceCollection[T]:
        return cls(items=(), availability=EvidenceAvailability.UNAVAILABLE, reason=reason)


@dataclass(frozen=True, slots=True)
class PositionFact:
    """Read-only position facts copied from the canonical fill-accounting ledger."""

    instrument: InstrumentId
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal
    fees: Decimal
    effective_at: datetime

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("position effective_at must be timezone-aware")

    @classmethod
    def from_ledger_entry(
        cls,
        entry: PositionLedgerEntry,
        *,
        effective_at: datetime,
    ) -> PositionFact:
        return cls(
            instrument=entry.instrument,
            quantity=entry.quantity,
            average_price=entry.average_price,
            realized_pnl=entry.realized_pnl,
            fees=entry.fees,
            effective_at=effective_at,
        )


@dataclass(frozen=True, slots=True)
class OpenOrderFact:
    """Stable read-only order inventory entry; UNKNOWN remains unresolved."""

    client_order_id: str
    instrument: InstrumentId
    status: OrderStatus
    order_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal | None
    created_at: datetime
    evidence_time: datetime | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity must be between zero and order_quantity")
        if self.remaining_quantity is not None and not (
            Decimal("0") <= self.remaining_quantity <= self.order_quantity
        ):
            raise ValueError("remaining_quantity must be between zero and order_quantity")
        for name, value in (("created_at", self.created_at), ("evidence_time", self.evidence_time)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EngineEvidenceAdapter:
    """Normalized driver evidence input to the common strategy snapshot builder.

    Drivers own normalization and retention of raw receipts/fills. This value
    object carries only facts already normalized through canonical seams.
    """

    positions: EvidenceCollection[PositionFact]
    orders: EvidenceCollection[OpenOrderFact]
    account_state: HistoricalAccountStateSnapshot | None
    account_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EngineStateSnapshot:
    """Immutable positions, unresolved orders, and account evidence at one cut."""

    as_of: datetime
    positions: EvidenceCollection[PositionFact]
    orders: EvidenceCollection[OpenOrderFact]
    account_state: HistoricalAccountStateSnapshot | None
    account_availability: EvidenceAvailability
    account_reason: str | None = None

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("snapshot as_of must be timezone-aware")
        normalized_as_of = self.as_of.astimezone(UTC)
        object.__setattr__(self, "as_of", normalized_as_of)
        for position in self.positions.items:
            if position.effective_at.astimezone(UTC) > normalized_as_of:
                raise TemporalIntegrityError(
                    f"position evidence for {position.instrument} is later than snapshot as_of"
                )
        for order in self.orders.items:
            if (
                order.evidence_time is not None
                and order.evidence_time.astimezone(UTC) > normalized_as_of
            ):
                raise TemporalIntegrityError(
                    f"order evidence for {order.client_order_id} is later than snapshot as_of"
                )
        if self.account_state is None:
            if self.account_availability is not EvidenceAvailability.UNAVAILABLE:
                raise ValueError("missing account state must be unavailable")
            if not (self.account_reason and self.account_reason.strip()):
                raise ValueError("unavailable account state requires a reason")
        else:
            if (
                self.account_state.timestamp.astimezone(UTC) > normalized_as_of
            ):
                raise TemporalIntegrityError("account-state evidence is later than snapshot as_of")
            if (
                self.account_state.completeness is AccountStateCompleteness.COMPLETE
                and self.account_availability is not EvidenceAvailability.AVAILABLE
            ):
                raise ValueError("complete account state must be marked available")
            if (
                self.account_state.completeness is AccountStateCompleteness.INCOMPLETE
                and self.account_availability is EvidenceAvailability.AVAILABLE
            ):
                raise ValueError("incomplete account state cannot be marked available")
            if (
                self.account_availability is not EvidenceAvailability.AVAILABLE
                and not (self.account_reason and self.account_reason.strip())
            ):
                raise ValueError("incomplete account state requires a reason")


class TemporalIntegrityError(ValueError):
    """Raised when effective evidence falls after its declared information cut."""


def build_engine_snapshot(
    adapter: EngineEvidenceAdapter,
    *,
    as_of: datetime,
) -> EngineStateSnapshot:
    """Project already-normalized facts into the one immutable strategy snapshot."""
    account = adapter.account_state
    if account is None:
        account_availability = EvidenceAvailability.UNAVAILABLE
        account_reason = adapter.account_reason or "account-state evidence is unavailable"
    elif account.completeness is AccountStateCompleteness.COMPLETE:
        account_availability = EvidenceAvailability.AVAILABLE
        account_reason = None
    else:
        account_availability = EvidenceAvailability.INCOMPLETE
        account_reason = adapter.account_reason or account.issue or "account valuation is incomplete"
    return EngineStateSnapshot(
        as_of=as_of,
        positions=adapter.positions,
        orders=adapter.orders,
        account_state=account,
        account_availability=account_availability,
        account_reason=account_reason,
    )


def unavailable_engine_snapshot(as_of: datetime, reason: str) -> EngineStateSnapshot:
    """Return explicit UNKNOWN dimensions for evaluation without driver evidence."""
    if not reason.strip():
        raise ValueError("unavailable snapshot reason must not be empty")
    return EngineStateSnapshot(
        as_of=as_of,
        positions=EvidenceCollection.unavailable(reason),
        orders=EvidenceCollection.unavailable(reason),
        account_state=None,
        account_availability=EvidenceAvailability.UNAVAILABLE,
        account_reason=reason,
    )


def position_facts(
    entries: tuple[PositionLedgerEntry, ...],
    *,
    effective_at: datetime,
) -> tuple[PositionFact, ...]:
    """Stamp canonical ledger read views with the inventory snapshot's effective cut."""
    return tuple(
        PositionFact.from_ledger_entry(entry, effective_at=effective_at)
        for entry in entries
    )


def prior_candle_history(
    candles: tuple[Candle, ...],
    *,
    instrument: InstrumentId,
    as_of: datetime,
    limit: int,
) -> tuple[Candle, ...]:
    """Return the most recent same-instrument candles strictly before as_of."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("history as_of must be timezone-aware")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 512:
        raise ValueError("history_bars must be an integer between 0 and 512")
    if limit == 0:
        return ()
    eligible = tuple(
        candle
        for candle in candles
        if (
            candle.instrument == instrument
            and candle.timestamp.astimezone(UTC) < as_of.astimezone(UTC)
        )
    )
    return eligible[-limit:]


def active_order_fact(
    *,
    client_order_id: str,
    instrument: InstrumentId,
    status: OrderStatus,
    order_quantity: Decimal,
    filled_quantity: Decimal,
    created_at: datetime,
    evidence_time: datetime,
    reason: str | None = None,
) -> OpenOrderFact | None:
    """Build a retained inventory fact, omitting only canonical terminal statuses."""
    if is_terminal_order_status(status):
        return None
    return OpenOrderFact(
        client_order_id=client_order_id,
        instrument=instrument,
        status=status,
        order_quantity=order_quantity,
        filled_quantity=filled_quantity,
        remaining_quantity=order_quantity - filled_quantity,
        created_at=created_at,
        evidence_time=evidence_time,
        reason=reason,
    )
