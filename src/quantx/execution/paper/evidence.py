"""Evidence-aware outcomes for simulated execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SimulationEvidenceStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SimulationEvidence:
    status: SimulationEvidenceStatus
    reason: str
    source_timestamp_ns: int | None = None

    @property
    def is_confirmed(self) -> bool:
        return self.status is SimulationEvidenceStatus.CONFIRMED
