"""Event-aware historical replay primitives.

The replay layer keeps lifecycle/adjustment/roll events explicit. It does not
mutate historical observations implicitly; callers receive an event context
that can be consumed by strategy, execution, or accounting policy layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable


class EventReplayKind(StrEnum):
    INSTRUMENT_LIFECYCLE = "INSTRUMENT_LIFECYCLE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    CONTRACT_ROLL = "CONTRACT_ROLL"


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    event_id: str
    timestamp: datetime
    kind: EventReplayKind
    instrument_id: str
    payload: tuple[tuple[str, str], ...] = ()
    source_id: str = ""
    version: str = "1"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("event timestamp must be timezone-aware")
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be empty")


@dataclass(frozen=True, slots=True)
class ReplayEventContext:
    as_of: datetime
    events: tuple[ReplayEvent, ...]
    adjustment_policy: str
    adjustment_policy_version: str
    roll_policy: str
    roll_policy_version: str


class EventReplayCatalog:
    """Deterministic point-in-time event lookup without look-ahead."""

    def __init__(self, events: Iterable[ReplayEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda item: (item.timestamp, item.event_id)))

    def as_of(self, timestamp: datetime, instrument_id: str) -> tuple[ReplayEvent, ...]:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return tuple(
            event
            for event in self._events
            if event.instrument_id == instrument_id and event.timestamp <= timestamp
        )
