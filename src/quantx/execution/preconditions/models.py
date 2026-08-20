"""Execution precondition results used before routing/submission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PreconditionsStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PreconditionsResult:
    status: PreconditionsStatus
    reasons: tuple[str, ...] = ()

    @property
    def can_execute(self) -> bool:
        return self.status is PreconditionsStatus.READY
