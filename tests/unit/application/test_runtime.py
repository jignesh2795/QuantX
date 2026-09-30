"""Tests for the explicit application startup lifecycle."""

from datetime import UTC, datetime

import pytest

from quantx.application.pending_recovery import PendingRecoveryResult, PendingRecoveryRun
from quantx.application.runtime import ApplicationRuntime


class FakeRecovery:
    def __init__(self, report: PendingRecoveryRun) -> None:
        self.report = report
        self.calls = 0
        self.checked_at = None

    def run(self, *, checked_at=None) -> PendingRecoveryRun:
        self.calls += 1
        self.checked_at = checked_at
        return self.report


def test_runtime_runs_pending_recovery_once() -> None:
    checked_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    recovery = FakeRecovery(
        PendingRecoveryRun(
            (
                PendingRecoveryResult("order-1", True),
                PendingRecoveryResult("order-2", False, error="broker unavailable"),
            )
        )
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=checked_at)

    assert runtime.started
    assert recovery.calls == 1
    assert recovery.checked_at == checked_at
    assert result.recovered == 1
    assert result.pending == 0
    assert result.failed == 1

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start(checked_at=checked_at)
    assert recovery.calls == 1


def test_runtime_rejects_naive_startup_timestamp() -> None:
    runtime = ApplicationRuntime(
        pending_recovery=FakeRecovery(PendingRecoveryRun())
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        runtime.start(checked_at=datetime(2026, 1, 1, 12))


def test_runtime_does_not_mark_started_when_recovery_raises() -> None:
    class ExplodingRecovery:
        def run(self, *, checked_at=None):
            raise RuntimeError("recovery infrastructure unavailable")

    runtime = ApplicationRuntime(pending_recovery=ExplodingRecovery())

    with pytest.raises(RuntimeError, match="recovery infrastructure unavailable"):
        runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
