"""Composable fail-closed execution precondition evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .models import PreconditionsResult, PreconditionsStatus


@dataclass(frozen=True, slots=True)
class ExecutionPrecondition:
    name: str
    check: Callable[[], bool | None]

    def evaluate(self) -> bool | None:
        return self.check()


class PreconditionEvaluator:
    """Evaluate independent evidence checks without collapsing UNKNOWN into PASS."""

    def evaluate(self, checks: Iterable[ExecutionPrecondition]) -> PreconditionsResult:
        blocked: list[str] = []
        unknown: list[str] = []
        for check in checks:
            result = check.evaluate()
            if result is False:
                blocked.append(check.name)
            elif result is None:
                unknown.append(check.name)

        if blocked:
            return PreconditionsResult(PreconditionsStatus.BLOCKED, tuple(blocked + unknown))
        if unknown:
            return PreconditionsResult(PreconditionsStatus.UNKNOWN, tuple(unknown))
        return PreconditionsResult(PreconditionsStatus.READY)


def execution_ready_from_evidence(
    *,
    account_state_status: str | None,
    position_state_status: str | None,
    connection_health: str | None,
    required_capabilities_ok: bool | None,
) -> PreconditionsResult:
    """Convert integration evidence into canonical execution preconditions.

    Missing evidence is UNKNOWN, not PASS. PAPER is explicitly accepted as an
    account-state source because it is configured simulation state rather than
    an invented live balance.
    """

    def known_status(value: str | None, accepted: set[str]) -> bool | None:
        if value is None:
            return None
        return value in accepted

    return PreconditionEvaluator().evaluate(
        (
            ExecutionPrecondition(
                "account_state",
                lambda: known_status(account_state_status, {"MATCHED", "PAPER"}),
            ),
            ExecutionPrecondition(
                "position_state",
                lambda: None if position_state_status is None else position_state_status == "MATCHED",
            ),
            ExecutionPrecondition(
                "connection_health",
                lambda: None if connection_health is None else connection_health == "HEALTHY",
            ),
            ExecutionPrecondition(
                "required_capabilities",
                lambda: required_capabilities_ok,
            ),
        )
    )
