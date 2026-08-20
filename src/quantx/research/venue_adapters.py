"""Plugin boundary for versioned market/venue rules.

Global and jurisdiction-specific implementations live outside the universal core.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VenueRuleContext:
    venue: str
    effective_from: datetime
    effective_to: datetime | None
    rule_version: str
    minimum_order_value: Decimal | None = None
    minimum_quantity: Decimal | None = None
    capabilities: frozenset[str] = frozenset()


class VenueRuleProvider(Protocol):
    """Resolve the rule set effective at an exact historical timestamp."""

    def resolve(self, venue: str, timestamp: datetime) -> VenueRuleContext | None: ...


@dataclass(frozen=True, slots=True)
class StaticVenueRuleProvider:
    """Deterministic provider useful for tests and local development."""

    rules: tuple[VenueRuleContext, ...]

    def resolve(self, venue: str, timestamp: datetime) -> VenueRuleContext | None:
        matches = [
            rule for rule in self.rules
            if rule.venue == venue
            and rule.effective_from <= timestamp
            and (rule.effective_to is None or timestamp < rule.effective_to)
        ]
        if not matches:
            return None
        return max(matches, key=lambda rule: rule.effective_from)
