"""Explicit operator closure for unresolvable PENDING reservations.

This is the domain/application contract a future CLI/UI can call. It is the
only escape hatch when automated broker evidence cannot become definitive:
an authorized operator explicitly closes the unresolved reservation with an
audited identity and reason.

The operation performs no broker calls, creates no ExecutionReceipt, never
resubmits, and commits the audit record atomically inside one UnitOfWork
transaction. Recovery never invokes this path automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from quantx.execution.idempotency import OperatorResolution, OperatorResolutionAction
from quantx.persistence import UnitOfWork


def resolve_pending_operator(
    *,
    unit_of_work: UnitOfWork,
    client_order_id: UUID,
    request_fingerprint: str,
    operator_id: str,
    reason: str,
    resolved_at: datetime | None = None,
    action: OperatorResolutionAction = OperatorResolutionAction.CLOSE_UNRESOLVED,
    evidence_reference: str | None = None,
) -> OperatorResolution:
    """Close a PENDING reservation with an audited operator record.

    Fail-closed: the reservation must exist, still be PENDING (not completed
    or already resolved), and the fingerprint must match. Empty operator
    identity or reason is rejected before any state is touched. Repeated
    resolution never overwrites history.
    """
    if not isinstance(operator_id, str) or not operator_id.strip():
        raise ValueError("operator identity must not be empty")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("operator resolution reason must not be empty")
    observed_at = resolved_at or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("resolved_at must be timezone-aware")
    with unit_of_work:
        return unit_of_work.idempotency.resolve_operator(
            client_order_id,
            request_fingerprint,
            operator_id=operator_id,
            reason=reason,
            resolved_at=observed_at,
            action=action,
            evidence_reference=evidence_reference,
        )


__all__ = ["resolve_pending_operator"]
