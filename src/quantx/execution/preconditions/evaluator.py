"""Composable fail-closed precondition evaluation."""

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
    """Evaluate independent checks without collapsing UNKNOWN into PASS."""

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
