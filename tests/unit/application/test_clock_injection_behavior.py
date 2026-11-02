"""Behavioral clock-injection regressions for Issue #198."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from quantx.application.execution import (
    BrokerPreflightRejected,
    ExecutionDispatchStatus,
    ExecutionOrchestrator,
)
from quantx.application.operator_resolution import resolve_pending_operator
from quantx.application.pending_reconciliation import reconcile_pending_execution
from quantx.application.pending_recovery import (
    PendingExecutionRecoveryRunner,
    PendingRecoveryResult,
)
from quantx.application.production import (
    ProductionRuntimeConfig,
    build_production_runtime,
)
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.clock import FixedClock
from quantx.execution.receipts.quarantine import QuarantineObservationKind
from tests.unit.application.test_pending_reconciliation import _request

_CHECKED_AT = datetime(2026, 4, 5, 9, 30, tzinfo=UTC)


class _FakeRecovery:
    def __init__(self) -> None:
        self.checked_at = None
        self.clock = None

    def run(self, *, checked_at=None, clock=None):
        self.checked_at = checked_at
        self.clock = clock
        from quantx.application.pending_recovery import PendingRecoveryRun

        return PendingRecoveryRun(())


def test_application_startup_uses_injected_clock() -> None:
    fixed = FixedClock(_CHECKED_AT)
    recovery = _FakeRecovery()
    runtime = ApplicationRuntime(pending_recovery=recovery, clock=fixed)

    result = runtime.start()

    assert recovery.checked_at == fixed.now()
    assert result.pending == 0


def test_application_startup_checked_at_override_wins_over_clock() -> None:
    override = datetime(2026, 4, 6, 10, 0, tzinfo=UTC)
    recovery = _FakeRecovery()
    runtime = ApplicationRuntime(pending_recovery=recovery, clock=FixedClock(_CHECKED_AT))

    runtime.start(checked_at=override, clock=FixedClock(override))

    assert recovery.checked_at == override


def test_pending_recovery_uses_injected_clock() -> None:
    fixed = FixedClock(_CHECKED_AT)
    captured: dict[str, object] = {}

    class CapturingRunner(PendingExecutionRecoveryRunner):
        def _recover_one(self, context, checked_at, clock=None):  # type: ignore[override]
            captured["checked_at"] = checked_at
            captured["clock"] = clock
            return PendingRecoveryResult("order-1", True)

    runner = CapturingRunner(
        unit_of_work=SimpleNamespace(),
        provider_resolver=lambda request: None,  # type: ignore[arg-type]
        policy_verifier=SimpleNamespace(),
        clock=fixed,
    )
    runner._unit_of_work = SimpleNamespace(
        idempotency=SimpleNamespace(
            list_pending_recovery_records=lambda: [SimpleNamespace(error=None, context=object())]
        )
    )

    report = runner.run()

    assert captured["checked_at"] == fixed.now()
    assert captured["clock"] is fixed
    assert report.structurally_valid


def test_pending_reconciliation_uses_injected_time() -> None:
    from quantx.application.evidence_refresh import ReconciliationEvidenceRefresher

    fixed = FixedClock(_CHECKED_AT)
    captured: dict[str, object] = {}

    def spy_refresh(self, *args, **kwargs):
        captured["checked_at"] = kwargs.get("checked_at")
        return SimpleNamespace(definitive=False, broker_order=None)

    original = ReconciliationEvidenceRefresher.refresh
    ReconciliationEvidenceRefresher.refresh = spy_refresh
    try:
        outcome = reconcile_pending_execution(
            _request(),
            fingerprint="fingerprint-1",
            local_order=None,
            broker_order=None,
            provider=SimpleNamespace(),  # type: ignore[arg-type]
            unit_of_work=SimpleNamespace(),
            checked_at=None,
            clock=fixed,
        )
    finally:
        ReconciliationEvidenceRefresher.refresh = original

    assert captured["checked_at"] == fixed.now()
    assert outcome.definitive is False


def test_operator_resolution_records_injected_time() -> None:
    fixed = FixedClock(_CHECKED_AT)
    captured: dict[str, object] = {}

    class FakeIdempotency:
        def resolve_operator(self, *args, **kwargs):
            captured["resolved_at"] = kwargs.get("resolved_at")
            return SimpleNamespace()

    class FakeUnitOfWork:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        idempotency = FakeIdempotency()

    resolve_pending_operator(
        unit_of_work=FakeUnitOfWork(),
        client_order_id=uuid4(),
        request_fingerprint="fingerprint-1",
        operator_id="operator-1",
        reason="manual resolution",
        resolved_at=None,
        clock=fixed,
    )

    assert captured["resolved_at"] == fixed.now()


def test_execution_preflight_uses_injected_clock() -> None:
    fixed = FixedClock(_CHECKED_AT)
    captured: dict[str, object] = {}

    class FakeIdempotency:
        def record_not_submitted(self, *args, **kwargs):
            captured["recorded_at"] = kwargs.get("recorded_at")

    class FakeUnitOfWork:
        idempotency = FakeIdempotency()

    request = _request()
    orchestrator = ExecutionOrchestrator(
        policy_verifier=__import__(
            "tests.unit._execution_request_proofs", fromlist=["policy_verifier"]
        ).policy_verifier(),
        clock=fixed,
    )

    result = orchestrator._handle_preflight_rejection(
        request,
        FakeUnitOfWork(),
        "fingerprint-1",
        BrokerPreflightRejected("preflight rejected"),
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert captured["recorded_at"] == fixed.now()


def test_execution_quarantine_uses_injected_clock() -> None:
    fixed = FixedClock(_CHECKED_AT)
    captured: dict[str, object] = {}

    class FakeRecorder:
        def record(self, observation):
            captured["observed_at"] = observation.observed_at

    request = _request()
    orchestrator = ExecutionOrchestrator(
        policy_verifier=__import__(
            "tests.unit._execution_request_proofs", fromlist=["policy_verifier"]
        ).policy_verifier(),
        clock=fixed,
    )
    orchestrator._submission_quarantine = FakeRecorder()

    orchestrator._record_quarantined_evidence(
        request,
        "fingerprint-1",
        kind=QuarantineObservationKind.TRANSPORT_UNCERTAIN,
        receipt=None,
        reason="transport uncertain",
    )

    assert captured["observed_at"] == fixed.now()


def test_execution_identity_bindings_are_preserved() -> None:
    fixed = FixedClock(_CHECKED_AT)
    sentinel = object()
    orchestrator = ExecutionOrchestrator(
        policy_verifier=__import__(
            "tests.unit._execution_request_proofs", fromlist=["policy_verifier"]
        ).policy_verifier(),
        live_broker=sentinel,
        clock=fixed,
    )
    request = _request()

    assert orchestrator._live_broker is sentinel
    assert orchestrator._clock is fixed
    assert request.execution_context.account_id == __import__(
        "quantx.domain.value_objects", fromlist=["AccountId"]
    ).AccountId("acct-1")
    assert request.execution_context.broker_connection_id == __import__(
        "quantx.domain.value_objects", fromlist=["BrokerConnectionId"]
    ).BrokerConnectionId("conn-1")


def test_production_runtime_propagates_configured_clock(tmp_path) -> None:
    from quantx.integrations.account_registry import AccountConnectionRegistry

    fixed = FixedClock(_CHECKED_AT)

    def configure_registry(registry: AccountConnectionRegistry) -> None:
        return None

    runtime = build_production_runtime(
        ProductionRuntimeConfig(
            database_path=tmp_path / "quantx.db",
            configure_registry=configure_registry,
            evidence_factory=lambda adapter, request: None,  # type: ignore[return-value]
            policy_verifier=__import__(
                "tests.unit._execution_request_proofs", fromlist=["policy_verifier"]
            ).policy_verifier(),
            clock=fixed,
        )
    )
    try:
        assert runtime.application._clock is fixed
    finally:
        runtime.close()
