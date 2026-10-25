"""Typed evidence contracts for account-wide LIVE risk.

These objects describe observations; they do not authenticate broker claims.
The application composition root must bind each observation to the configured
account and connection, validate completeness and freshness, and fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .instruments import Instrument
from .value_objects import AccountId, BrokerConnectionId, Money, ProductCode


class EvidenceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


class RealizedPnlSource(StrEnum):
    BROKER_REPORTED = "BROKER_REPORTED"
    QUANTX_LEDGER_WITH_BROKER_TRADE_BOOK = "QUANTX_LEDGER_WITH_BROKER_TRADE_BOOK"


class PositionSurface(StrEnum):
    POSITIONS = "POSITIONS"
    HOLDINGS = "HOLDINGS"
    MARKS = "MARKS"


@dataclass(frozen=True, slots=True)
class PositionSurfaceEvidence:
    surface: PositionSurface
    status: EvidenceStatus
    observed_at: datetime
    version: str
    provenance: str
    row_count: int

    def __post_init__(self) -> None:
        if type(self.surface) is not PositionSurface or type(self.status) is not EvidenceStatus:
            raise ValueError("position surface and status must use canonical enums")
        _require_aware(self.observed_at, "position surface observed_at")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("position surface row_count must be a non-negative int")
        if not self.version.strip() or not self.provenance.strip():
            raise ValueError("position surface version and provenance are required")


@dataclass(frozen=True, slots=True)
class RealizedDailyPnlEvidence:
    """One realized daily P&L observation.

    ``amount`` is present only for ``COMPLETE`` evidence. An unavailable or
    incomplete observation must not carry an amount or daily charges: missing
    data is not zero, and a partial sum must never be mistaken for an
    authoritative daily result. The builder still validates currency, scope,
    charges, and freshness for a complete observation.
    """

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    trading_day: date
    day_start_at: datetime
    as_of: datetime
    amount: Money | None
    charges_daily: Money | None
    source: RealizedPnlSource
    scope: str
    completeness: EvidenceStatus
    covered_surfaces: tuple[str, ...]
    uncaptured_activity: tuple[str, ...]
    version: str
    provenance: str

    def __post_init__(self) -> None:
        if type(self.trading_day) is not date:
            raise ValueError("P&L trading_day must be a date")
        if self.amount is not None and type(self.amount) is not Money:
            raise ValueError("P&L amount must use Money when supplied")
        if self.charges_daily is not None and type(self.charges_daily) is not Money:
            raise ValueError("P&L daily charges must use Money when supplied")
        if (
            type(self.source) is not RealizedPnlSource
            or type(self.completeness) is not EvidenceStatus
        ):
            raise ValueError("P&L source and completeness must use canonical enums")
        if type(self.covered_surfaces) is not tuple or type(self.uncaptured_activity) is not tuple:
            raise ValueError(
                "P&L covered_surfaces and uncaptured_activity must be immutable tuples"
            )
        if not self.covered_surfaces or any(
            type(item) is not str or not item.strip() for item in self.covered_surfaces
        ):
            raise ValueError("P&L covered_surfaces must identify at least one covered surface")
        _require_aware(self.day_start_at, "P&L day_start_at")
        _require_aware(self.as_of, "P&L as_of")
        if self.as_of < self.day_start_at:
            raise ValueError("P&L as_of must not precede day_start_at")
        if self.completeness is EvidenceStatus.COMPLETE:
            if self.amount is None:
                raise ValueError("COMPLETE P&L evidence requires a Money amount")
        else:
            if self.amount is not None:
                raise ValueError("non-COMPLETE P&L evidence must not carry an amount")
            if self.charges_daily is not None:
                raise ValueError("non-COMPLETE P&L evidence must not carry daily charges")
        if self.amount is not None:
            _require_finite_decimal(self.amount.amount, "P&L amount")
        if self.charges_daily is not None:
            _require_finite_decimal(self.charges_daily.amount, "daily charges")
            if self.charges_daily.amount < 0:
                raise ValueError("daily charges must not be negative")
            amount = self.amount
            if amount is None:
                raise ValueError("daily charges require a P&L amount")
            if self.charges_daily.currency != amount.currency:
                raise ValueError("daily charges and P&L must use the same currency")
        if not self.broker_id.strip() or not self.scope.strip():
            raise ValueError("P&L broker_id and scope are required")
        if not self.version.strip() or not self.provenance.strip():
            raise ValueError("P&L version and provenance are required")


@dataclass(frozen=True, slots=True)
class LivePositionEvidence:
    instrument: Instrument
    product: ProductCode
    quantity: Decimal
    average_price: Decimal
    mark_price: Decimal
    mark_observed_at: datetime
    mark_source: str
    currency: str

    def __post_init__(self) -> None:
        if type(self.instrument) is not Instrument or type(self.product) is not ProductCode:
            raise ValueError("position requires canonical Instrument and ProductCode")
        _require_finite_decimal(self.quantity, "position quantity")
        _require_finite_decimal(self.average_price, "position average_price")
        _require_finite_decimal(self.mark_price, "position mark_price")
        if self.quantity == 0:
            raise ValueError("flat positions must not appear in LivePositionEvidence")
        if self.average_price <= 0 or self.mark_price <= 0:
            raise ValueError("position average_price and mark_price must be positive")
        _require_aware(self.mark_observed_at, "position mark_observed_at")
        if not self.mark_source.strip() or not self.currency.strip():
            raise ValueError("position mark_source and currency are required")
        if self.instrument.currency != self.currency:
            raise ValueError("position currency must match canonical instrument currency")


@dataclass(frozen=True, slots=True)
class WholeAccountPositionEvidence:
    """Canonical book after adapter-owned positions/holdings reconciliation.

    The adapter aggregates additive vendor rows under its declared merge policy
    before constructing the book. The core rejects duplicate instrument/product
    keys rather than silently summing.

    ``blockers`` names every provider-semantic reason the observation cannot
    establish a complete book. A ``COMPLETE`` book must not declare blockers;
    non-``COMPLETE`` evidence keeps the reasons explicit instead of implying
    that an empty or partial surface is a zero book.
    """

    account_id: AccountId
    connection_id: BrokerConnectionId
    surfaces: tuple[PositionSurfaceEvidence, ...]
    positions: tuple[LivePositionEvidence, ...]
    completeness: EvidenceStatus
    merge_policy: str
    observed_at: datetime
    version: str
    provenance: str
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.surfaces) is not tuple or type(self.positions) is not tuple:
            raise ValueError("position surfaces and positions must be immutable tuples")
        if type(self.completeness) is not EvidenceStatus:
            raise ValueError("position book completeness must use EvidenceStatus")
        if any(type(item) is not PositionSurfaceEvidence for item in self.surfaces):
            raise ValueError("position surfaces must use PositionSurfaceEvidence")
        if any(type(item) is not LivePositionEvidence for item in self.positions):
            raise ValueError("positions must use LivePositionEvidence")
        _require_aware(self.observed_at, "position book observed_at")
        if not self.merge_policy.strip() or not self.version.strip() or not self.provenance.strip():
            raise ValueError("position merge_policy, version, and provenance are required")
        if type(self.blockers) is not tuple:
            raise ValueError("position blockers must be an immutable tuple")
        if any(type(blocker) is not str or not blocker.strip() for blocker in self.blockers):
            raise ValueError("position blockers must be non-empty strings")
        if self.completeness is EvidenceStatus.COMPLETE and self.blockers:
            raise ValueError("COMPLETE position evidence must not declare blockers")
        seen: set[tuple[object, ProductCode]] = set()
        for position in self.positions:
            key = (position.instrument.instrument_id, position.product)
            if key in seen:
                raise ValueError(
                    "duplicate instrument/product position requires explicit aggregation"
                )
            seen.add(key)
        surfaces = [item.surface for item in self.surfaces]
        if len(surfaces) != len(set(surfaces)):
            raise ValueError("position surfaces must not be duplicated")


@dataclass(frozen=True, slots=True)
class MarginEvidence:
    account_id: AccountId
    connection_id: BrokerConnectionId
    required_margin: Money
    available_margin: Money
    observed_at: datetime
    source: str
    completeness: EvidenceStatus
    version: str
    provenance: str

    def __post_init__(self) -> None:
        if type(self.completeness) is not EvidenceStatus:
            raise ValueError("margin completeness must use EvidenceStatus")
        if type(self.required_margin) is not Money or type(self.available_margin) is not Money:
            raise ValueError("margin observations must use Money")
        _require_aware(self.observed_at, "margin observed_at")
        for name, value in (
            ("required_margin", self.required_margin.amount),
            ("available_margin", self.available_margin.amount),
        ):
            _require_finite_decimal(value, name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.required_margin.currency != self.available_margin.currency:
            raise ValueError("required and available margin must use the same currency")
        if not self.source.strip() or not self.version.strip() or not self.provenance.strip():
            raise ValueError("margin source, version, and provenance are required")


@dataclass(frozen=True, slots=True)
class ReferencePriceEvidence:
    instrument: Instrument
    price: Decimal
    observed_at: datetime
    source: str
    currency: str

    def __post_init__(self) -> None:
        _require_finite_decimal(self.price, "reference price")
        if self.price <= 0:
            raise ValueError("reference price must be positive")
        _require_aware(self.observed_at, "reference price observed_at")
        if not self.source.strip() or not self.currency.strip():
            raise ValueError("reference price source and currency are required")
        if self.instrument.currency != self.currency:
            raise ValueError("reference price currency must match canonical instrument currency")


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _require_finite_decimal(value: object, name: str) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")


__all__ = [
    "EvidenceStatus",
    "LivePositionEvidence",
    "MarginEvidence",
    "PositionSurface",
    "PositionSurfaceEvidence",
    "RealizedDailyPnlEvidence",
    "RealizedPnlSource",
    "ReferencePriceEvidence",
    "WholeAccountPositionEvidence",
]
