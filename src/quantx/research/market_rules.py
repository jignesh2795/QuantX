"""Point-in-time market and instrument metadata for historical research.

The universal instrument identity remains market-neutral. Historical research
selects a versioned rule/contract record by timestamp instead of assuming that
current metadata was valid in the past.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class TradabilityStatus(StrEnum):
    TRADABLE = "TRADABLE"
    NOT_LISTED = "NOT_LISTED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VersionedInstrumentRule:
    instrument_id: str
    effective_from: datetime
    effective_to: datetime | None
    tick_size: Decimal
    lot_size: Decimal
    multiplier: Decimal
    currency: str
    status: TradabilityStatus = TradabilityStatus.TRADABLE
    rule_version: str = "1"

    def __post_init__(self) -> None:
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")
        if self.tick_size <= 0 or self.lot_size <= 0 or self.multiplier <= 0:
            raise ValueError("tick_size, lot_size, and multiplier must be positive")
        if not self.currency.strip() or not self.rule_version.strip():
            raise ValueError("currency and rule_version must not be empty")

    def applies_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self.effective_from <= timestamp and (
            self.effective_to is None or timestamp < self.effective_to
        )


class PointInTimeInstrumentRegistry:
    """Select exactly one versioned instrument rule at a historical timestamp."""

    def __init__(self, rules: tuple[VersionedInstrumentRule, ...] = ()) -> None:
        self._rules: dict[str, tuple[VersionedInstrumentRule, ...]] = {}
        for rule in rules:
            self.add(rule)

    def add(self, rule: VersionedInstrumentRule) -> None:
        existing = self._rules.setdefault(rule.instrument_id, ())
        for other in existing:
            if self._overlaps(rule, other):
                raise ValueError(
                    f"overlapping instrument rules for {rule.instrument_id}"
                )
        self._rules[rule.instrument_id] = tuple(
            sorted((*existing, rule), key=lambda item: item.effective_from)
        )

    def resolve(self, instrument_id: str, timestamp: datetime) -> VersionedInstrumentRule:
        candidates = [
            rule for rule in self._rules.get(instrument_id, ()) if rule.applies_at(timestamp)
        ]
        if len(candidates) != 1:
            raise LookupError(
                f"no unique point-in-time rule for {instrument_id} at {timestamp.isoformat()}"
            )
        return candidates[0]

    @staticmethod
    def _overlaps(a: VersionedInstrumentRule, b: VersionedInstrumentRule) -> bool:
        a_end = a.effective_to or datetime.max.replace(tzinfo=a.effective_from.tzinfo)
        b_end = b.effective_to or datetime.max.replace(tzinfo=b.effective_from.tzinfo)
        return a.effective_from < b_end and b.effective_from < a_end


@dataclass(frozen=True, slots=True)
class PointInTimeTradability:
    instrument_id: str
    timestamp: datetime
    status: TradabilityStatus
    rule_version: str

    @property
    def tradable(self) -> bool:
        return self.status is TradabilityStatus.TRADABLE


def resolve_tradability(
    registry: PointInTimeInstrumentRegistry,
    instrument_id: str,
    timestamp: datetime,
) -> PointInTimeTradability:
    rule = registry.resolve(instrument_id, timestamp)
    return PointInTimeTradability(
        instrument_id=instrument_id,
        timestamp=timestamp,
        status=rule.status,
        rule_version=rule.rule_version,
    )
