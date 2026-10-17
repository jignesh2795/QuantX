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
from uuid import UUID

from quantx.domain.execution_request import PendingExecutionRecoveryRequest
from quantx.domain.orders import Fill
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.idempotency import PendingExecutionContext
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
)
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
from quantx.persistence import UnitOfWork

from .evidence_refresh import (
    DefinitiveEvidencePolicy,
    EvidenceRefreshOutcome,
    ReconciliationEvidenceProvider,
    RefreshPolicy,
    is_advisory_account_amount_evidence,
)
from .not_found_policy import NotFoundResolution
from .pending_reconciliation import reconcile_pending_execution
from .reconciliation import OrderStateReconciliationResult, OrderWorkflowStatus


@dataclass(frozen=True, slots=True)
class PendingRecoveryResult:
    """Outcome for one persisted pending execution context.

    A definitive claim is only valid when it is backed by definitive outcome
    evidence: ``definitive`` must be the real boolean ``True``, ``outcome``
    must be the canonical refresh outcome whose nested reconciliation result
    is structurally valid and semantically consistent with the reconciliation
    contract, ``client_order_id`` must be a non-empty record identity, and
    ``error`` must be absent. The record identity, the nested result order
    identity, and the outcome's broker observation must all name the same
    order. Contradictory or malformed combinations are never counted as
    resolved.
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
    Records whose identity is unusable or whose definitive claim is not backed
    by valid nested evidence are never counted as resolved.
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


def _is_str_tuple(value: object) -> bool:
    return isinstance(value, tuple) and all(isinstance(item, str) for item in value)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _has_record_identity(result: PendingRecoveryResult) -> bool:
    """True only for a non-blank string client_order_id."""
    client_order_id = result.client_order_id
    return isinstance(client_order_id, str) and client_order_id.strip() != ""


def _outcome_structurally_valid(outcome: EvidenceRefreshOutcome) -> bool:
    """True only when the refresh outcome fields carry their canonical types."""
    if not _is_non_negative_int(outcome.attempts):
        return False
    if not _is_str_tuple(outcome.refreshed_domains):
        return False
    if not _is_str_tuple(outcome.reasons):
        return False
    if outcome.broker_order is not None and not isinstance(outcome.broker_order, OrderObservation):
        return False
    if outcome.broker_position is not None and not isinstance(
        outcome.broker_position, PositionState
    ):
        return False
    if outcome.broker_account is not None and not isinstance(
        outcome.broker_account, AccountFinancialState
    ):
        return False
    if outcome.not_found_eligibility is not None and not isinstance(
        outcome.not_found_eligibility, NotFoundResolution
    ):
        return False
    return True


def _result_structurally_valid(result: OrderStateReconciliationResult) -> bool:
    """True only when the nested reconciliation result carries canonical types."""
    if not isinstance(result.status, OrderWorkflowStatus):
        return False
    if result.identity_error is not None and not isinstance(result.identity_error, str):
        return False
    if not _is_str_tuple(result.reasons):
        return False
    if result.order_id is not None and not isinstance(result.order_id, UUID):
        return False
    if result.account_id is not None and not isinstance(result.account_id, AccountId):
        return False
    if result.connection_id is not None and not isinstance(
        result.connection_id, BrokerConnectionId
    ):
        return False
    if result.broker_order_id is not None and not isinstance(result.broker_order_id, str):
        return False
    order = result.order
    if order is not None and (
        not isinstance(order, OrderReconciliationResult)
        or not isinstance(order.status, OrderReconciliationStatus)
        or not isinstance(order.order_id, UUID)
    ):
        return False
    position = result.position
    if position is not None and (
        not isinstance(position, PositionReconciliation)
        or not isinstance(position.status, PositionReconciliationStatus)
    ):
        return False
    account = result.account
    if account is not None and (
        not isinstance(account, ReconciliationReport)
        or not isinstance(account.status, AccountReconciliationStatus)
        or not isinstance(account.findings, tuple)
        or not all(isinstance(finding, ReconciliationFinding) for finding in account.findings)
    ):
        return False
    return True


def _evidence_scope_matches_result(
    result: OrderStateReconciliationResult,
    evidence_account_id: AccountId,
    evidence_connection_id: BrokerConnectionId,
) -> bool:
    """True when evidence scope cannot conflict with the nested result scope.

    The canonical workflow sets ``identity_error`` whenever collected position
    or account evidence names a different account or connection than the
    execution receipt, so a consistent nested result can never carry
    conflicting evidence scope. Scope bindings the result does not carry are
    not constrained.
    """
    if result.account_id is not None and evidence_account_id != result.account_id:
        return False
    if result.connection_id is not None and evidence_connection_id != result.connection_id:
        return False
    return True


def _definitive_result_consistent(result: object) -> bool:
    """True only for a canonical nested result that can back a definitive outcome.

    Every definitive claim requires a matched order whose own order identity
    equals the result identity, no identity failure, and position evidence
    that is matched or absent with scope matching the result context. The
    MATCHED aggregate also requires absent or matched account evidence. The
    MISMATCH aggregate is definitive only under the advisory-amounts contract:
    the account mismatch must be present, scope consistent, and limited to
    both-sides balance deltas. UNKNOWN and INCOMPLETE aggregates, unresolved
    or mismatched positions, matched accounts, conflicting evidence scope,
    identity failures, and order-identity disagreement never back a
    definitive outcome.
    """
    if not isinstance(result, OrderStateReconciliationResult):
        return False
    if not _result_structurally_valid(result):
        return False
    if result.identity_error is not None:
        return False
    order = result.order
    if order is None or order.status is not OrderReconciliationStatus.MATCHED:
        return False
    if result.order_id is None or order.order_id != result.order_id:
        return False
    position = result.position
    if position is not None:
        if position.status.value != "MATCHED":
            return False
        if not _evidence_scope_matches_result(result, position.account_id, position.connection_id):
            return False
    account = result.account
    if account is not None and not _evidence_scope_matches_result(
        result, account.account_id, account.connection_id
    ):
        return False
    if result.status is OrderWorkflowStatus.MATCHED:
        return account is None or account.status.value == "MATCHED"
    if result.status is OrderWorkflowStatus.MISMATCH:
        if account is None or account.status.value != "MISMATCH":
            return False
        return is_advisory_account_amount_evidence(account)
    return False


def _canonical_record_order_id(client_order_id: object) -> UUID | None:
    """Return the order UUID a canonical recovery-record identity carries.

    The canonical runner identifies each pending record by
    ``str(order.client_order_id)``, so a canonical record identity is exactly
    a string that parses as a UUID and round-trips through ``str`` unchanged.
    Anything else can never back a definitive resolution.
    """
    if not isinstance(client_order_id, str):
        return None
    try:
        parsed = UUID(client_order_id)
    except ValueError:
        return None
    if str(parsed) != client_order_id:
        return None
    return parsed


def _record_binds_nested_result(result: PendingRecoveryResult, nested: object) -> bool:
    """True when the record identity and nested order identity name one order.

    The canonical resolution path refuses to resolve a pending reservation
    unless the nested result order identity equals the receipt order identity,
    which is the record identity. A record that names one order while its
    nested evidence names another is contradictory and never resolved.
    """
    record_order_id = _canonical_record_order_id(result.client_order_id)
    if record_order_id is None:
        return False
    return isinstance(nested, OrderStateReconciliationResult) and nested.order_id == record_order_id


def _definitive_evidence_consistent(outcome: EvidenceRefreshOutcome) -> bool:
    """True only when the nested result is bound to its broker observation.

    A matched order can only be produced from both local and broker
    observations carrying the same order id, and the canonical refresh
    outcome surfaces that same broker observation. A definitive outcome with
    missing broker observation or a disagreeing broker order identity is
    contradictory and never resolved; broker identifiers the result does not
    carry are not constrained.
    """
    nested = outcome.result
    if not _definitive_result_consistent(nested):
        return False
    assert isinstance(nested, OrderStateReconciliationResult)
    broker_order = outcome.broker_order
    if not isinstance(broker_order, OrderObservation):
        return False
    if broker_order.order_id != nested.order_id:
        return False
    if (
        nested.broker_order_id is not None
        and broker_order.broker_order_id is not None
        and nested.broker_order_id != broker_order.broker_order_id
    ):
        return False
    return True


def _has_definitive_evidence(result: PendingRecoveryResult) -> bool:
    outcome = result.outcome
    if not isinstance(outcome, EvidenceRefreshOutcome) or outcome.definitive is not True:
        return False
    if not _outcome_structurally_valid(outcome):
        return False
    if not _definitive_evidence_consistent(outcome):
        return False
    return _record_binds_nested_result(result, outcome.result)


def _is_resolved(result: PendingRecoveryResult) -> bool:
    return (
        _has_record_identity(result)
        and result.definitive is True
        and result.error is None
        and _has_definitive_evidence(result)
    )


def _is_pending(result: PendingRecoveryResult) -> bool:
    return _has_record_identity(result) and result.definitive is not True and result.error is None


def _is_failed(result: PendingRecoveryResult) -> bool:
    if not _has_record_identity(result):
        return True
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
