"""Application operation reconciling one pending execution against broker evidence.

The caller supplies the pending client order context explicitly because
PENDING reservations do not contain the original execution request. Broker
evidence is fetched outside any database transaction; only the final local
resolution (receipt save plus idempotency resolution) shares one UnitOfWork
transaction. Non-definitive evidence leaves PENDING untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
)
from quantx.domain.orders import Fill
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    ReconciliationPolicy,
)
from quantx.persistence import UnitOfWork

from .evidence_refresh import (
    DefinitiveEvidencePolicy,
    EvidenceRefreshOutcome,
    ReconciliationEvidenceProvider,
    ReconciliationEvidenceRefresher,
    ReconciliationIdempotencyResolver,
    RefreshPolicy,
)
from .uncertain_submission import UncertainSubmissionReceiptRecovery


def reconcile_pending_execution(
    request: ApprovedExecutionRequest | PendingExecutionRecoveryRequest,
    *,
    fingerprint: str,
    local_order: OrderObservation | None,
    broker_order: OrderObservation | None,
    fills: tuple[Fill, ...] = (),
    provider: ReconciliationEvidenceProvider,
    unit_of_work: UnitOfWork,
    checked_at: datetime | None = None,
    evidence_policy: DefinitiveEvidencePolicy | None = None,
    refresh_policy: RefreshPolicy | None = None,
    position_policy: ReconciliationPolicy | None = None,
    local_position: PositionState | None = None,
    broker_position: PositionState | None = None,
    local_account: AccountFinancialState | None = None,
    broker_account: AccountFinancialState | None = None,
    instrument_id: str | None = None,
) -> EvidenceRefreshOutcome:
    """Reconcile one pending execution; resolve it only on definitive evidence."""
    observed_at = checked_at or datetime.now(UTC)
    broker_reference: str | None
    if local_order is not None and local_order.broker_order_id is not None:
        broker_reference = local_order.broker_order_id
    elif broker_order is not None:
        broker_reference = broker_order.broker_order_id
    else:
        broker_reference = None
    provisional = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=OrderStatus.UNKNOWN,
        executed_at=observed_at,
        broker_order_id=broker_reference,
        order_id=request.order.client_order_id,
        account_id=request.execution_context.account_id,
        connection_id=request.execution_context.broker_connection_id,
    )
    refresher = ReconciliationEvidenceRefresher(
        refresh_policy=refresh_policy, evidence_policy=evidence_policy
    )
    outcome = refresher.refresh(
        provisional,
        local_order=local_order,
        broker_order=broker_order,
        local_position=local_position,
        broker_position=broker_position,
        local_account=local_account,
        broker_account=broker_account,
        checked_at=observed_at,
        position_policy=position_policy,
        instrument_id=instrument_id,
        provider=provider,
    )
    if not outcome.definitive or outcome.broker_order is None:
        return outcome
    receipt = UncertainSubmissionReceiptRecovery().recover(
        request,
        outcome.broker_order,
        request_id=uuid4(),
        recovered_at=observed_at,
        fills=fills,
    )
    if receipt is None:
        return outcome
    with unit_of_work:
        unit_of_work.receipts.save(receipt)
        ReconciliationIdempotencyResolver.resolve(
            outcome,
            receipt,
            request_fingerprint=fingerprint,
            idempotency=unit_of_work.idempotency,
        )
    return outcome
