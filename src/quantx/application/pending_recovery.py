"""Boot-time orchestration for durable pending LIVE execution recovery.

This module only consumes persisted PENDING execution contexts and invokes
reconciliation. It never submits broker orders. A provider resolver keeps broker
selection outside the recovery workflow while preserving account/connection
identity from the persisted execution context.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from quantx.domain.execution_request import PendingExecutionRecoveryRequest
from quantx.domain.orders import Fill
from quantx.execution.idempotency import PendingExecutionContext
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
)
from quantx.persistence import UnitOfWork

from .evidence_refresh import (
    DefinitiveEvidencePolicy,
    EvidenceRefreshOutcome,
    ReconciliationEvidenceProvider,
    RefreshPolicy,
)
from .pending_reconciliation import reconcile_pending_execution


@dataclass(frozen=True, slots=True)
class PendingRecoveryResult:
    """Outcome for one persisted pending execution context.

    A definitive claim is only valid when it is backed by definitive outcome
    evidence: ``definitive`` must be the real boolean ``True``, ``outcome``
    must be the canonical refresh outcome, and ``error`` must be absent.
    Contradictory combinations are never counted as resolved.
    """

    client_order_id: str
    definitive: bool
    outcome: EvidenceRefreshOutcome | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PendingRecoveryRun:
    """Deterministic summary of one pending-recovery pass.

    ``results`` must be the immutable tuple produced by the recovery runner.
    Any other container, and any element that is not a ``PendingRecoveryResult``,
    makes the report structurally invalid so startup readiness can never be
    granted from it; malformed reports remain constructible and inspectable.
    """

    results: tuple[PendingRecoveryResult, ...] = ()

    @property
    def structurally_valid(self) -> bool:
        """True only for a tuple of well-formed recovery results."""
        results = self.results
        if not isinstance(results, tuple):
            return False
        return all(isinstance(result, PendingRecoveryResult) for result in results)

    @property
    def fully_resolved(self) -> bool:
        """True only when well formed and every record resolved definitively."""
        return self.structurally_valid and all(_is_resolved(result) for result in self.results)

    @property
    def attempted(self) -> int:
        return len(self._records)

    @property
    def resolved(self) -> int:
        return sum(1 for result in self._records if _is_resolved(result))

    @property
    def pending(self) -> int:
        return sum(1 for result in self._records if _is_pending(result))

    @property
    def failed(self) -> int:
        return sum(1 for result in self._records if _is_failed(result))

    @property
    def _records(self) -> tuple[PendingRecoveryResult, ...]:
        """Well-formed records only; unsupported structures count nothing here."""
        results = self.results
        if not isinstance(results, tuple):
            return ()
        return tuple(result for result in results if isinstance(result, PendingRecoveryResult))


def _has_definitive_evidence(result: PendingRecoveryResult) -> bool:
    outcome = result.outcome
    return isinstance(outcome, EvidenceRefreshOutcome) and outcome.definitive is True


def _is_resolved(result: PendingRecoveryResult) -> bool:
    return result.definitive is True and result.error is None and _has_definitive_evidence(result)


def _is_pending(result: PendingRecoveryResult) -> bool:
    return result.definitive is not True and result.error is None


def _is_failed(result: PendingRecoveryResult) -> bool:
    if result.error is not None:
        return True
    return result.definitive is True and not _has_definitive_evidence(result)


ProviderResolver = Callable[
    [PendingExecutionRecoveryRequest],
    ReconciliationEvidenceProvider,
]
LocalOrderProvider = Callable[
    [PendingExecutionRecoveryRequest],
    OrderObservation | None,
]
LocalPositionProvider = Callable[
    [PendingExecutionRecoveryRequest],
    PositionState | None,
]
LocalAccountProvider = Callable[
    [PendingExecutionRecoveryRequest],
    AccountFinancialState | None,
]
FillProvider = Callable[
    [PendingExecutionRecoveryRequest, OrderObservation | None],
    tuple[Fill, ...],
]


class PendingExecutionRecoveryRunner:
    """Recover all durable pending LIVE executions without resubmission."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        provider_resolver: ProviderResolver,
        local_order_provider: LocalOrderProvider | None = None,
        local_position_provider: LocalPositionProvider | None = None,
        local_account_provider: LocalAccountProvider | None = None,
        fill_provider: FillProvider | None = None,
        evidence_policy: DefinitiveEvidencePolicy | None = None,
        refresh_policy: RefreshPolicy | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider_resolver = provider_resolver
        self._local_order_provider = local_order_provider
        self._local_position_provider = local_position_provider
        self._local_account_provider = local_account_provider
        self._fill_provider = fill_provider
        self._evidence_policy = evidence_policy
        self._refresh_policy = refresh_policy

    def run(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> PendingRecoveryRun:
        observed_at = checked_at or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

        pending_records = self._unit_of_work.idempotency.list_pending_recovery_records()
        results: list[PendingRecoveryResult] = []
        for record in pending_records:
            if record.error is not None:
                results.append(
                    PendingRecoveryResult(
                        record.client_order_id,
                        False,
                        error=f"pending recovery failed safely: {record.error}",
                    )
                )
                continue
            assert record.context is not None
            results.append(self._recover_one(record.context, observed_at))
        return PendingRecoveryRun(tuple(results))

    def _recover_one(
        self,
        context: PendingExecutionContext,
        checked_at: datetime,
    ) -> PendingRecoveryResult:
        request = context.to_recovery_request()
        client_order_id = str(request.order.client_order_id)
        try:
            provider = self._provider_resolver(request)
            local_order = (
                None if self._local_order_provider is None else self._local_order_provider(request)
            )
            local_position = (
                None
                if self._local_position_provider is None
                else self._local_position_provider(request)
            )
            local_account = (
                None
                if self._local_account_provider is None
                else self._local_account_provider(request)
            )
            fills = () if self._fill_provider is None else self._fill_provider(request, local_order)
            outcome = reconcile_pending_execution(
                request,
                fingerprint=context.request_fingerprint,
                local_order=local_order,
                broker_order=None,
                fills=fills,
                provider=provider,
                unit_of_work=self._unit_of_work,
                checked_at=checked_at,
                evidence_policy=self._evidence_policy or DefinitiveEvidencePolicy.live_recovery(),
                local_position=local_position,
                local_account=local_account,
                refresh_policy=self._refresh_policy,
                instrument_id=str(request.order.instrument),
            )
            return PendingRecoveryResult(
                client_order_id,
                outcome.definitive,
                outcome=outcome,
            )
        except Exception as exc:
            return PendingRecoveryResult(
                client_order_id,
                False,
                error=f"pending recovery failed safely: {exc}",
            )


def recover_pending_live_executions(
    *,
    unit_of_work: UnitOfWork,
    provider_resolver: ProviderResolver,
    local_order_provider: LocalOrderProvider | None = None,
    local_position_provider: LocalPositionProvider | None = None,
    local_account_provider: LocalAccountProvider | None = None,
    fill_provider: FillProvider | None = None,
    checked_at: datetime | None = None,
    evidence_policy: DefinitiveEvidencePolicy | None = None,
    refresh_policy: RefreshPolicy | None = None,
) -> PendingRecoveryRun:
    """Convenience boot hook for one deterministic pending-recovery pass."""
    return PendingExecutionRecoveryRunner(
        unit_of_work=unit_of_work,
        provider_resolver=provider_resolver,
        local_order_provider=local_order_provider,
        local_position_provider=local_position_provider,
        local_account_provider=local_account_provider,
        fill_provider=fill_provider,
        evidence_policy=evidence_policy,
        refresh_policy=refresh_policy,
    ).run(checked_at=checked_at)
