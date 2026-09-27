"""Explicit historical adjustment policies and provenance.

Raw observations are never silently rewritten. Adjustments are represented as
explicit transformations with a versioned policy and source event identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class AdjustmentPolicy(StrEnum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
    EVENT_RECONSTRUCTED = "EVENT_RECONSTRUCTED"


@dataclass(frozen=True, slots=True)
class AdjustmentEvent:
    event_id: str
    event_type: str
    effective_at: datetime
    factor: Decimal = Decimal("1")
    source_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.event_type.strip():
            raise ValueError("event_type must not be empty")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        if self.factor <= 0:
            raise ValueError("factor must be positive")


@dataclass(frozen=True, slots=True)
class AdjustmentProvenance:
    policy: AdjustmentPolicy
    policy_version: str
    event_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


class HistoricalAdjuster:
    """Apply only explicitly supplied adjustments; never infer missing events."""

    def apply(
        self,
        value: Decimal,
        events: tuple[AdjustmentEvent, ...],
        *,
        policy: AdjustmentPolicy,
        as_of: datetime | None = None,
    ) -> tuple[Decimal, AdjustmentProvenance]:
        if policy is AdjustmentPolicy.RAW:
            return value, AdjustmentProvenance(policy, "raw-v1")
        if as_of is None:
            raise ValueError("as_of is required for adjusted historical values")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        adjusted = value
        ordered_events = tuple(
            event
            for event in sorted(events, key=lambda item: (item.effective_at, item.event_id))
            if event.effective_at <= as_of
        )
        for event in ordered_events:
            adjusted *= event.factor
        version = "adjusted-v1" if policy is AdjustmentPolicy.ADJUSTED else "event-reconstructed-v1"
        return adjusted, AdjustmentProvenance(
            policy,
            version,
            tuple(event.event_id for event in ordered_events),
            tuple(event.source_id for event in ordered_events if event.source_id),
        )
