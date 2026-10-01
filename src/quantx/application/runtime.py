"""Explicit application startup lifecycle with pending LIVE recovery.

The runtime owns one-shot startup orchestration. It has no broker transport
and no background worker; pending recovery is supplied as an application
dependency so startup wiring remains explicit and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .pending_recovery import PendingRecoveryRun


class StartupRecoveryHook(Protocol):
    """Application startup hook for durable pending LIVE recovery."""

    def run(self, *, checked_at: datetime | None = None) -> PendingRecoveryRun: ...


@dataclass(frozen=True, slots=True)
class ApplicationStartupResult:
    """Deterministic result returned after one application startup pass."""

    pending_recovery: PendingRecoveryRun

    @property
    def pending(self) -> int:
        return self.pending_recovery.pending

    @property
    def failed(self) -> int:
        return self.pending_recovery.failed

    @property
    def recovered(self) -> int:
        return self.pending_recovery.resolved


class ApplicationRuntime:
    """Run explicit startup recovery exactly once."""

    def __init__(self, *, pending_recovery: StartupRecoveryHook) -> None:
        self._pending_recovery = pending_recovery
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> ApplicationStartupResult:
        """Run startup recovery once, then mark the runtime started."""
        if self._started:
            raise RuntimeError("application runtime is already started")

        observed_at = checked_at or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

        recovery = self._pending_recovery.run(checked_at=observed_at)
        self._started = True
        return ApplicationStartupResult(pending_recovery=recovery)
