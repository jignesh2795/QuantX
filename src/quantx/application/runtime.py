"""Explicit application startup lifecycle with pending LIVE recovery.

The runtime owns one-shot startup orchestration. It has no broker transport
and no background worker; pending recovery is supplied as an application
dependency so startup wiring remains explicit and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from quantx.domain.clock import Clock, SystemClock

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
        """True only when the recovery report is well formed and fully resolved."""
        recovery = self.pending_recovery
        if not isinstance(recovery, PendingRecoveryRun):
            return False
        return recovery.fully_resolved


class ApplicationRuntime:
    """Run explicit startup recovery until it resolves definitively.

    Readiness is granted only by a structurally valid, complete recovery
    report in which every record resolved definitively with definitive
    outcome evidence. Unresolved or malformed reports leave the runtime
    unstarted while remaining inspectable through ``last_startup_result``;
    the operator may explicitly start again to rerun recovery after
    remediation (for example operator resolution of the pending reservation).
    Once successfully started, repeated startup is rejected. A recovery-hook
    exception or a report of the wrong type propagates and likewise leaves
    readiness false.
    """

    def __init__(
        self, *, pending_recovery: StartupRecoveryHook, clock: Clock | None = None
    ) -> None:
        self._pending_recovery = pending_recovery
        self._clock = clock if clock is not None else SystemClock()
        if not isinstance(self._clock, Clock):
            raise TypeError("application runtime requires a Clock")
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
        clock: Clock | None = None,
    ) -> ApplicationStartupResult:
        """Run startup recovery and grant readiness only when it resolves.

        Returns the complete recovery report either way and retains it for
        inspection. A report with pending, failed, or malformed records leaves
        the runtime unstarted without submitting orders, retrying, or altering
        any reservation; the caller may retry explicitly after remediation.
        """
        if self._started:
            raise RuntimeError("application runtime is already started")

        active_clock = clock if clock is not None else self._clock
        if not isinstance(active_clock, Clock):
            raise TypeError("application runtime requires a Clock")
        observed_at = checked_at if checked_at is not None else active_clock.now()
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
