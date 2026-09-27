"""Versioned broker/venue rule boundary for historical and live execution.

The universal domain asks for capabilities and explicit constraints; market/broker
plugins supply the concrete rules for a venue and point in time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class RuleStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VenueRuleSnapshot:
    venue: str
    version: str
    effective_from: datetime
    effective_to: datetime | None = None
    minimum_order_value: Decimal | None = None
    minimum_quantity: Decimal | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.venue.strip() or not self.version.strip():
            raise ValueError("venue and version must not be empty")
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")
        if self.minimum_order_value is not None and self.minimum_order_value <= 0:
            raise ValueError("minimum_order_value must be positive")
        if self.minimum_quantity is not None and self.minimum_quantity <= 0:
            raise ValueError("minimum_quantity must be positive")


class VenueRuleProvider(Protocol):
    def resolve(self, venue: str, timestamp: datetime) -> VenueRuleSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class StaticVenueRuleProvider:
    rules: tuple[VenueRuleSnapshot, ...]

    def __post_init__(self) -> None:
        for index, rule in enumerate(self.rules):
            for other in self.rules[index + 1 :]:
                if rule.venue == other.venue and self._overlaps(rule, other):
                    raise ValueError(f"overlapping venue rules for {rule.venue}")

    def resolve(self, venue: str, timestamp: datetime) -> VenueRuleSnapshot | None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        candidates = [
            rule
            for rule in self.rules
            if rule.venue == venue
            and rule.effective_from <= timestamp
            and (rule.effective_to is None or timestamp < rule.effective_to)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda rule: (rule.effective_from, rule.version), reverse=True)
        return candidates[0]

    @staticmethod
    def _overlaps(a: VenueRuleSnapshot, b: VenueRuleSnapshot) -> bool:
        a_end = a.effective_to or datetime.max.replace(tzinfo=a.effective_from.tzinfo)
        b_end = b.effective_to or datetime.max.replace(tzinfo=b.effective_from.tzinfo)
        return a.effective_from < b_end and b.effective_from < a_end


def evaluate_order_constraints(
    rule: VenueRuleSnapshot,
    *,
    order_value: Decimal,
    quantity: Decimal,
) -> tuple[RuleStatus, tuple[str, ...]]:
    issues: list[str] = []
    if order_value <= 0:
        issues.append("order value must be positive")
    if quantity <= 0:
        issues.append("quantity must be positive")
    if rule.minimum_order_value is not None and order_value < rule.minimum_order_value:
        issues.append("order value is below venue minimum")
    if rule.minimum_quantity is not None and quantity < rule.minimum_quantity:
        issues.append("quantity is below venue minimum")
    return (RuleStatus.INVALID if issues else RuleStatus.VALID, tuple(issues))
