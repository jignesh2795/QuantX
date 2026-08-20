"""Explicit futures/derivatives roll mechanics for historical research.

Roll decisions are policy-driven. QuantX never silently switches contracts or
manufactures a roll price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from decimal import Decimal

from quantx.domain.value_objects import InstrumentId


class RollMethod(StrEnum):
    NONE = "NONE"
    CALENDAR = "CALENDAR"
    VOLUME = "VOLUME"
    OPEN_INTEREST = "OPEN_INTEREST"
    EXPLICIT = "EXPLICIT"


@dataclass(frozen=True, slots=True)
class ContractRollRule:
    rule_id: str
    version: str
    method: RollMethod
    roll_before_expiry_days: int | None = None
    ratio_adjustment: Decimal | None = None
    additive_adjustment: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.version.strip():
            raise ValueError("roll rule identity must not be empty")
        if self.roll_before_expiry_days is not None and self.roll_before_expiry_days < 0:
            raise ValueError("roll_before_expiry_days cannot be negative")
        if self.ratio_adjustment is not None and self.ratio_adjustment <= 0:
            raise ValueError("ratio_adjustment must be positive")


@dataclass(frozen=True, slots=True)
class ContractRollEvent:
    timestamp: datetime
    from_instrument: InstrumentId
    to_instrument: InstrumentId
    method: RollMethod
    rule_id: str
    rule_version: str
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    adjustment: Decimal | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.from_instrument == self.to_instrument:
            raise ValueError("roll must change instrument")


@dataclass(frozen=True, slots=True)
class RollDecision:
    timestamp: datetime
    active_instrument: InstrumentId
    next_instrument: InstrumentId | None
    should_roll: bool
    rule_id: str
    rule_version: str
    reason: str


class ExplicitRollSchedule:
    """Historical roll schedule with no inference from missing data."""

    def __init__(self, events: tuple[ContractRollEvent, ...]) -> None:
        self._events = tuple(sorted(events, key=lambda event: event.timestamp))

    def decision_at(self, timestamp: datetime, active_instrument: InstrumentId) -> RollDecision:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        for event in self._events:
            if event.timestamp <= timestamp and event.from_instrument == active_instrument:
                return RollDecision(
                    timestamp=timestamp,
                    active_instrument=active_instrument,
                    next_instrument=event.to_instrument,
                    should_roll=True,
                    rule_id=event.rule_id,
                    rule_version=event.rule_version,
                    reason="explicit historical roll event",
                )
        return RollDecision(
            timestamp=timestamp,
            active_instrument=active_instrument,
            next_instrument=None,
            should_roll=False,
            rule_id="NONE",
            rule_version="NONE",
            reason="no explicit roll event available",
        )
