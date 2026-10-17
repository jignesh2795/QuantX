"""Tests for the explicit application startup lifecycle."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from quantx.application.evidence_refresh import EvidenceRefreshOutcome
from quantx.application.pending_recovery import PendingRecoveryResult, PendingRecoveryRun
from quantx.application.reconciliation import (
    OrderStateReconciliationResult,
    OrderWorkflowStatus,
)
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.reconciliation.account import (
    ReconciliationFinding,
    ReconciliationReport,
)
from quantx.integrations.reconciliation.account import (
    ReconciliationStatus as AccountReconciliationStatus,
)
from quantx.integrations.reconciliation.orders import (
    OrderReconciliationResult,
    OrderReconciliationStatus,
)
from quantx.integrations.reconciliation.positions import PositionReconciliation
from quantx.integrations.reconciliation.positions import (
    ReconciliationStatus as PositionReconciliationStatus,
)

_ACCOUNT_ID = AccountId("account-1")
_CONNECTION_ID = BrokerConnectionId("connection-1")
_ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
_CHECKED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_UNSET: object = object()


def _order_result(
    status: OrderReconciliationStatus = OrderReconciliationStatus.MATCHED,
) -> OrderReconciliationResult:
    return OrderReconciliationResult(_ORDER_ID, status, "order state matches")


def _position_result(
    status: PositionReconciliationStatus = PositionReconciliationStatus.MATCHED,
) -> PositionReconciliation:
    return PositionReconciliation(
        _ACCOUNT_ID,
        _CONNECTION_ID,
        "NSE:TCS",
        status,
        Decimal("1"),
        Decimal("1"),
        _CHECKED_AT,
        "position quantity reconciled",
    )


def _account_report(
    status: AccountReconciliationStatus = AccountReconciliationStatus.MATCHED,
    findings: tuple[ReconciliationFinding, ...] = (),
) -> ReconciliationReport:
    return ReconciliationReport(_ACCOUNT_ID, _CONNECTION_ID, status, findings)


def _advisory_account_report() -> ReconciliationReport:
    return _account_report(
        AccountReconciliationStatus.MISMATCH,
        (ReconciliationFinding("available_cash", "100", "101", "available_cash differs"),),
    )


def _identity_account_report() -> ReconciliationReport:
    return _account_report(
        AccountReconciliationStatus.MISMATCH,
        (ReconciliationFinding("identity", "a", "b", "account/connection identity mismatch"),),
    )


def _reconciliation_result(**overrides: object) -> OrderStateReconciliationResult:
    base: dict[str, object] = {
        "order_id": _ORDER_ID,
        "account_id": _ACCOUNT_ID,
        "connection_id": _CONNECTION_ID,
        "broker_order_id": "broker-1",
        "order": _order_result(),
        "position": _position_result(),
        "account": _account_report(),
        "status": OrderWorkflowStatus.MATCHED,
        "reasons": (),
        "identity_error": None,
    }
    base.update(overrides)
    return OrderStateReconciliationResult(**base)


def _outcome(
    *,
    definitive: bool,
    result: object = _UNSET,
    **overrides: object,
) -> EvidenceRefreshOutcome:
    base: dict[str, object] = {
        "result": _reconciliation_result() if result is _UNSET else result,
        "attempts": 0,
        "refreshed_domains": (),
        "definitive": definitive,
    }
    base.update(overrides)
    return EvidenceRefreshOutcome(**base)


def _resolved(client_order_id: str) -> PendingRecoveryResult:
    return PendingRecoveryResult(client_order_id, True, outcome=_outcome(definitive=True))


def _unresolved(client_order_id: str) -> PendingRecoveryResult:
    return PendingRecoveryResult(
        client_order_id,
        False,
        outcome=_outcome(
            definitive=False,
            result=_reconciliation_result(status=OrderWorkflowStatus.UNKNOWN),
        ),
    )


class FakeRecovery:
    def __init__(self, report: PendingRecoveryRun) -> None:
        self.report = report
        self.calls = 0
        self.checked_at = None

    def run(self, *, checked_at=None) -> PendingRecoveryRun:
        self.calls += 1
        self.checked_at = checked_at
        return self.report


def test_runtime_starts_when_recovery_fully_resolves() -> None:
    checked_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    recovery = FakeRecovery(PendingRecoveryRun((_resolved("order-1"), _resolved("order-2"))))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=checked_at)

    assert runtime.started
    assert result.ready is True
    assert recovery.calls == 1
    assert recovery.checked_at == checked_at
    assert result.recovered == 2
    assert result.pending == 0
    assert result.failed == 0
    assert runtime.last_startup_result == result

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start(checked_at=checked_at)
    assert recovery.calls == 1


def test_runtime_stays_unready_when_recovery_fails() -> None:
    recovery = FakeRecovery(
        PendingRecoveryRun((PendingRecoveryResult("order-1", False, error="broker unavailable"),))
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 0
    assert result.failed == 1
    assert runtime.last_startup_result == result


def test_runtime_stays_unready_when_recovery_pending() -> None:
    recovery = FakeRecovery(PendingRecoveryRun((_unresolved("order-1"),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 1
    assert result.failed == 0
    assert runtime.last_startup_result == result


def test_runtime_mixed_recovery_preserves_evidence_and_stays_unready() -> None:
    report = PendingRecoveryRun(
        (
            _resolved("order-1"),
            _unresolved("order-2"),
            PendingRecoveryResult("order-3", False, error="broker unavailable"),
        )
    )
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(report))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 1
    assert result.pending == 1
    assert result.failed == 1
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery.results == report.results


def test_runtime_retry_after_unready_startup_is_allowed() -> None:
    """An unready runtime may be started again; success stays one-shot."""
    reports = [
        PendingRecoveryRun((PendingRecoveryResult("order-1", False, error="broker unavailable"),)),
        PendingRecoveryRun((_resolved("order-1"),)),
    ]
    calls = 0

    class ScriptedRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            nonlocal calls
            report = reports[calls]
            calls += 1
            return report

    runtime = ApplicationRuntime(pending_recovery=ScriptedRecovery())

    first = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert not runtime.started
    assert first.ready is False

    second = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert runtime.started
    assert second.ready is True
    assert runtime.last_startup_result == second

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert calls == 2


def test_runtime_rejects_malformed_recovery_report() -> None:
    class MalformedRecovery:
        def run(self, *, checked_at=None):
            return {"resolved": ["order-1"]}

    runtime = ApplicationRuntime(pending_recovery=MalformedRecovery())

    with pytest.raises(TypeError, match="PendingRecoveryRun"):
        runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert runtime.last_startup_result is None


def test_runtime_rejects_naive_startup_timestamp() -> None:
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(PendingRecoveryRun()))

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


def test_runtime_rejects_non_bool_definitive_int() -> None:
    """definitive=1 (int) must not bypass readiness; treated as non-definitive."""
    recovery = FakeRecovery(PendingRecoveryRun((PendingRecoveryResult("order-1", 1),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 1
    assert result.failed == 0


def test_runtime_rejects_non_bool_definitive_str() -> None:
    """definitive="yes" (str) must not bypass readiness; treated as non-definitive."""
    recovery = FakeRecovery(PendingRecoveryRun((PendingRecoveryResult("order-1", "yes"),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 1
    assert result.failed == 0


def test_runtime_rejects_non_bool_definitive_none() -> None:
    """definitive=None must not bypass readiness; treated as non-definitive."""
    recovery = FakeRecovery(PendingRecoveryRun((PendingRecoveryResult("order-1", None),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 1
    assert result.failed == 0


def test_runtime_rejects_definitive_without_outcome_evidence() -> None:
    """A definitive claim without outcome evidence must never grant readiness."""
    recovery = FakeRecovery(PendingRecoveryRun((PendingRecoveryResult("order-1", True),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 0
    assert result.pending == 0
    assert result.failed == 1
    assert runtime.last_startup_result is result


def test_runtime_rejects_definitive_with_non_definitive_outcome_evidence() -> None:
    """Outcome evidence that is not definitive cannot support a definitive claim."""
    recovery = FakeRecovery(
        PendingRecoveryRun(
            (PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=False)),)
        )
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 0
    assert result.failed == 1
    assert runtime.last_startup_result is result


def test_runtime_rejects_definitive_with_foreign_outcome_evidence() -> None:
    """Outcome evidence of the wrong type cannot support a definitive claim."""
    recovery = FakeRecovery(
        PendingRecoveryRun((PendingRecoveryResult("order-1", True, outcome="resolved"),))
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 0
    assert result.failed == 1
    assert runtime.last_startup_result is result


def test_runtime_rejects_contradictory_definitive_error() -> None:
    """definitive=True with error is contradictory; treated as non-ready."""
    recovery = FakeRecovery(
        PendingRecoveryRun((PendingRecoveryResult("order-1", True, error="broker unavailable"),))
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 0
    assert result.failed == 1


def test_runtime_rejects_definitive_with_error_and_definitive_outcome() -> None:
    """Error evidence always fails, even with otherwise definitive outcome evidence."""
    recovery = FakeRecovery(
        PendingRecoveryRun(
            (
                PendingRecoveryResult(
                    "order-1",
                    True,
                    outcome=_outcome(definitive=True),
                    error="broker unavailable",
                ),
            )
        )
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 0
    assert result.pending == 0
    assert result.failed == 1


def test_runtime_rejects_list_results_container() -> None:
    """A results list is not the supported tuple container and never grants readiness."""
    report = PendingRecoveryRun(results=[_resolved("order-1")])
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(report))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery is report


def test_runtime_rejects_none_results_container() -> None:
    """A None results container is unsupported and never grants readiness."""
    report = PendingRecoveryRun(results=None)
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(report))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 0
    assert result.failed == 0
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery is report


def test_runtime_rejects_dict_results_container() -> None:
    """A dict results container is unsupported and never grants readiness."""
    report = PendingRecoveryRun(results={"order-1": _resolved("order-1")})
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(report))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery is report


def test_runtime_rejects_malformed_element_in_valid_report() -> None:
    """A non-result element inside an otherwise valid report blocks readiness."""
    report = PendingRecoveryRun((_resolved("order-1"), object()))
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(report))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery is report


def test_runtime_valid_empty_report_ready() -> None:
    """Empty recovery report (no results) must leave runtime ready."""
    recovery = FakeRecovery(PendingRecoveryRun())
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert runtime.started
    assert result.ready is True
    assert result.recovered == 0
    assert result.pending == 0
    assert result.failed == 0


def test_runtime_report_retention_after_unready() -> None:
    """The complete latest report must remain inspectable after an unsuccessful start."""
    recovery = FakeRecovery(
        PendingRecoveryRun((PendingRecoveryResult("order-1", False, error="broker unavailable"),))
    )
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery.results == recovery.report.results


def test_runtime_retry_after_unready_with_malformed() -> None:
    """An unready runtime with malformed definitive may be explicitly started again."""
    reports = [
        PendingRecoveryRun((PendingRecoveryResult("order-1", 1),)),
        PendingRecoveryRun((_resolved("order-1"),)),
    ]
    calls = 0

    class ScriptedRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            nonlocal calls
            report = reports[calls]
            calls += 1
            return report

    runtime = ApplicationRuntime(pending_recovery=ScriptedRecovery())

    first = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert not runtime.started
    assert first.ready is False

    second = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert runtime.started
    assert second.ready is True
    assert runtime.last_startup_result == second

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))
    assert calls == 2


_MALFORMED_DEFINITIVE_RECORDS: tuple[PendingRecoveryResult, ...] = (
    PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=True, result=None)),
    PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=True, result="definitive")),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(status=OrderWorkflowStatus.UNKNOWN),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(status=OrderWorkflowStatus.INCOMPLETE),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(definitive=True, result=_reconciliation_result(status="MATCHED")),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(definitive=True, result=_reconciliation_result(order_id="not-a-uuid")),
    ),
    PendingRecoveryResult(None, True, outcome=_outcome(definitive=True)),
    PendingRecoveryResult("", True, outcome=_outcome(definitive=True)),
    PendingRecoveryResult("   ", True, outcome=_outcome(definitive=True)),
    PendingRecoveryResult(123, True, outcome=_outcome(definitive=True)),
    PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=True, attempts="many")),
    PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=True, attempts=-1)),
    PendingRecoveryResult(
        "order-1", True, outcome=_outcome(definitive=True, refreshed_domains=["order"])
    ),
    PendingRecoveryResult("order-1", True, outcome=_outcome(definitive=True, reasons="done")),
    PendingRecoveryResult(
        "order-1", True, outcome=_outcome(definitive=True, broker_order="snapshot")
    ),
    PendingRecoveryResult(
        "order-1", True, outcome=_outcome(definitive=True, broker_position="position")
    ),
    PendingRecoveryResult(
        "order-1", True, outcome=_outcome(definitive=True, broker_account="account")
    ),
    PendingRecoveryResult(
        "order-1", True, outcome=_outcome(definitive=True, not_found_eligibility="eligible")
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(definitive=True, result=_reconciliation_result(order=None)),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(
                order=_order_result(OrderReconciliationStatus.STATE_MISMATCH)
            ),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(definitive=True, result=_reconciliation_result(order="order")),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(
                position=_position_result(PositionReconciliationStatus.MISMATCH)
            ),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(position=_position_result(status="MATCHED")),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(definitive=True, result=_reconciliation_result(position="position")),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(account=_identity_account_report()),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(
                status=OrderWorkflowStatus.MISMATCH,
                identity_error="broker order identity does not match execution receipt",
                account=_advisory_account_report(),
            ),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(status=OrderWorkflowStatus.MISMATCH, account=None),
        ),
    ),
    PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(
                status=OrderWorkflowStatus.MISMATCH,
                account=_identity_account_report(),
            ),
        ),
    ),
)

_MALFORMED_DEFINITIVE_IDS: tuple[str, ...] = (
    "nested-result-none",
    "nested-result-foreign",
    "nested-status-unknown",
    "nested-status-incomplete",
    "nested-status-raw-string",
    "nested-order-id-foreign",
    "identity-none",
    "identity-empty",
    "identity-blank",
    "identity-int",
    "attempts-foreign-string",
    "attempts-negative",
    "refreshed-domains-list",
    "reasons-foreign-string",
    "broker-order-foreign",
    "broker-position-foreign",
    "broker-account-foreign",
    "not-found-eligibility-foreign",
    "matched-without-order",
    "matched-with-unmatched-order",
    "matched-with-foreign-order",
    "matched-with-unmatched-position",
    "matched-with-raw-position-status",
    "matched-with-foreign-position",
    "matched-with-unmatched-account",
    "mismatch-with-identity-error",
    "mismatch-without-account",
    "mismatch-with-non-advisory-account",
)


@pytest.mark.parametrize(
    "record",
    _MALFORMED_DEFINITIVE_RECORDS,
    ids=_MALFORMED_DEFINITIVE_IDS,
)
def test_runtime_rejects_definitive_with_malformed_nested_evidence(
    record: PendingRecoveryResult,
) -> None:
    """Malformed, contradictory, or wrongly typed nested evidence never resolves."""
    recovery = FakeRecovery(PendingRecoveryRun((record,)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.recovered == 0
    assert result.pending == 0
    assert result.failed == 1
    retained = runtime.last_startup_result
    assert retained is not None
    assert retained.pending_recovery is recovery.report


def test_runtime_malformed_identity_counts_failed_not_pending() -> None:
    """A record without a usable identity can never be pending or resolved."""
    recovery = FakeRecovery(PendingRecoveryRun((PendingRecoveryResult(None, False),)))
    runtime = ApplicationRuntime(pending_recovery=recovery)

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert not runtime.started
    assert result.ready is False
    assert result.pending == 0
    assert result.failed == 1


def test_runtime_accepts_definitive_advisory_account_mismatch() -> None:
    """A mismatch caused solely by advisory balance deltas is a supported
    definitive outcome and must keep resolving."""
    record = PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            result=_reconciliation_result(
                status=OrderWorkflowStatus.MISMATCH,
                account=_advisory_account_report(),
            ),
        ),
    )
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(PendingRecoveryRun((record,))))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert runtime.started
    assert result.ready is True
    assert result.recovered == 1
    assert result.failed == 0


def test_runtime_accepts_definitive_with_refresh_trail() -> None:
    """Canonical refresh metadata on a definitive outcome never blocks readiness."""
    record = PendingRecoveryResult(
        "order-1",
        True,
        outcome=_outcome(
            definitive=True,
            attempts=2,
            refreshed_domains=("order", "position", "account"),
            reasons=(),
        ),
    )
    runtime = ApplicationRuntime(pending_recovery=FakeRecovery(PendingRecoveryRun((record,))))

    result = runtime.start(checked_at=datetime(2026, 1, 1, 12, tzinfo=UTC))

    assert runtime.started
    assert result.ready is True
    assert result.recovered == 1
