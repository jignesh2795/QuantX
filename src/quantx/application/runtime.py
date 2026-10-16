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

    @property
    def ready(self) -> bool:
        """True only when every recovery record resolved definitively."""
        return self.pending == 0 and self.failed == 0


class ApplicationRuntime:
    """Run explicit startup recovery until it resolves definitively.

    Readiness is granted only by a complete recovery report with zero pending
    and zero failed records. An unresolved report leaves the runtime
    unstarted; the operator may explicitly start again to rerun recovery
    after remediation (for example operator resolution of the pending
    reservation). Once successfully started, repeated startup is rejected.
    A recovery-hook exception propagates and likewise leaves readiness false.
    """

    def __init__(self, *, pending_recovery: StartupRecoveryHook) -> None:
        self._pending_recovery = pending_recovery
        self._started = False
        self._last_startup_result: ApplicationStartupResult | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def last_startup_result(self) -> ApplicationStartupResult | None:
        """The latest complete startup report, if any attempt has finished."""
        return self._last_startup_result

    def start(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> ApplicationStartupResult:
        """Run startup recovery and grant readiness only when it resolves.

        Returns the complete recovery report either way and retains it for
        inspection. A report with pending or failed records leaves the runtime
        unstarted without submitting orders, retrying, or altering any
        reservation; the caller may retry explicitly after remediation.
        """
        if self._started:
            raise RuntimeError("application runtime is already started")

        observed_at = checked_at or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

        recovery = self._pending_recovery.run(checked_at=observed_at)
        if not isinstance(recovery, PendingRecoveryRun):
            raise TypeError("startup recovery must return PendingRecoveryRun")
        result = ApplicationStartupResult(pending_recovery=recovery)
        self._last_startup_result = result
        if result.ready:
            self._started = True
        return result
