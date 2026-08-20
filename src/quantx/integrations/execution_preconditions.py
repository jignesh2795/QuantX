"""Execution preconditions combining account, position, and connection state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PreconditionStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ExecutionPreconditionResult:
    status: PreconditionStatus
    reasons: tuple[str, ...] = ()
    checked_at: datetime | None = None

    @property
    def is_ready(self) -> bool:
        return self.status is PreconditionStatus.READY


class ExecutionPreconditionChecker:
    """Fail closed when required account or position evidence is missing."""

    def check(
        self,
        *,
        account_state_status: str,
        position_state_status: str,
        connection_health: str,
        required_capabilities_ok: bool,
        checked_at: datetime | None = None,
    ) -> ExecutionPreconditionResult:
        reasons: list[str] = []
        if account_state_status not in {"MATCHED", "PAPER"}:
            reasons.append(f"account state not execution-ready: {account_state_status}")
        if position_state_status != "MATCHED":
            reasons.append(f"position state not reconciled: {position_state_status}")
        if connection_health not in {"HEALTHY"}:
            reasons.append(f"connection not healthy: {connection_health}")
        if not required_capabilities_ok:
            reasons.append("required broker capabilities are unavailable")
        status = PreconditionStatus.READY if not reasons else PreconditionStatus.BLOCKED
        return ExecutionPreconditionResult(status, tuple(reasons), checked_at)
