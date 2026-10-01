"""Point-in-time instrument lifecycle and corporate-action event rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class LifecycleStatus(StrEnum):
    NOT_LISTED = "NOT_LISTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class InstrumentLifecycle:
    instrument_id: str
    valid_from: datetime
    valid_to: datetime | None = None
    listing_status: LifecycleStatus = LifecycleStatus.ACTIVE
    rule_version: str = "1"

    def __post_init__(self) -> None:
        if self.valid_from.tzinfo is None or self.valid_from.utcoffset() is None:
            raise ValueError("valid_from must be timezone-aware")
        if self.valid_to is not None:
            if self.valid_to.tzinfo is None or self.valid_to.utcoffset() is None:
                raise ValueError("valid_to must be timezone-aware")
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must not precede valid_from")

    def contains(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self.valid_from <= timestamp and (self.valid_to is None or timestamp < self.valid_to)


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    event_id: str
    instrument_id: str
    effective_at: datetime
    event_type: str
    factor: Decimal | None = None
    cash_amount: Decimal | None = None
    adjustment_method: str = "UNADJUSTED"
    source_version: str = "1"

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        if self.factor is not None and self.factor <= 0:
            raise ValueError("factor must be positive")

    def applies_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return timestamp >= self.effective_at


@dataclass(frozen=True, slots=True)
class ContractLifecycle:
    instrument_id: str
    contract_rule_version: str
    listed_from: datetime
    expiry_at: datetime | None = None
    settled_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("listed_from", self.listed_from),
            ("expiry_at", self.expiry_at),
            ("settled_at", self.settled_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        if self.expiry_at is not None and self.expiry_at <= self.listed_from:
            raise ValueError("expiry_at must be after listed_from")
        if self.settled_at is not None:
            if self.expiry_at is None:
                raise ValueError("settled_at requires expiry_at")
            if self.settled_at < self.expiry_at:
                raise ValueError("settled_at must not precede expiry_at")

    def tradable_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if timestamp < self.listed_from:
            return False
        if self.expiry_at is not None and timestamp >= self.expiry_at:
            return False
        return True
