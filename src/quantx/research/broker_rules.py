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
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")


class VenueRuleProvider(Protocol):
    def resolve(self, venue: str, timestamp: datetime) -> VenueRuleSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class StaticVenueRuleProvider:
    rules: tuple[VenueRuleSnapshot, ...]

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


def evaluate_order_constraints(
    rule: VenueRuleSnapshot,
    *,
    order_value: Decimal,
    quantity: Decimal,
) -> tuple[RuleStatus, tuple[str, ...]]:
    issues: list[str] = []
    if rule.minimum_order_value is not None and order_value < rule.minimum_order_value:
        issues.append("order value is below venue minimum")
    if rule.minimum_quantity is not None and quantity < rule.minimum_quantity:
        issues.append("quantity is below venue minimum")
    return (RuleStatus.INVALID if issues else RuleStatus.VALID, tuple(issues))
