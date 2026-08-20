"""Position reconciliation and execution precondition implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class PositionState:
    account_id: UUID
    connection_id: UUID
    instrument_id: str
    quantity: Decimal
    average_price: Decimal | None
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("source must not be empty")


@dataclass(frozen=True, slots=True)
class PositionReconciliation:
    account_id: UUID
    connection_id: UUID
    instrument_id: str
    status: ReconciliationStatus
    local_quantity: Decimal | None
    observed_quantity: Decimal | None
    checked_at: datetime
    message: str


@dataclass(frozen=True, slots=True)
class ReconciliationPolicy:
    max_state_age: timedelta
    quantity_tolerance: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.max_state_age.total_seconds() < 0:
            raise ValueError("max_state_age cannot be negative")
        if self.quantity_tolerance < 0:
            raise ValueError("quantity_tolerance cannot be negative")


class PositionReconciler:
    """Compare local and observed positions without inventing missing state."""

    def reconcile(
        self,
        local: PositionState | None,
        observed: PositionState | None,
        *,
        checked_at: datetime,
        policy: ReconciliationPolicy,
    ) -> PositionReconciliation:
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if local is None or observed is None:
            account_id = observed.account_id if observed else local.account_id  # type: ignore[union-attr]
            connection_id = observed.connection_id if observed else local.connection_id  # type: ignore[union-attr]
            instrument_id = observed.instrument_id if observed else local.instrument_id  # type: ignore[union-attr]
            return PositionReconciliation(
                account_id, connection_id, instrument_id,
                ReconciliationStatus.INCOMPLETE,
                local.quantity if local else None,
                observed.quantity if observed else None,
                checked_at,
                "local or observed position state is missing",
            )
        if local.account_id != observed.account_id or local.connection_id != observed.connection_id:
            return PositionReconciliation(
                local.account_id, local.connection_id, local.instrument_id,
                ReconciliationStatus.MISMATCH,
                local.quantity, observed.quantity, checked_at,
                "account or connection identity mismatch",
            )
        if local.instrument_id != observed.instrument_id:
            return PositionReconciliation(
                local.account_id, local.connection_id, local.instrument_id,
                ReconciliationStatus.MISMATCH,
                local.quantity, observed.quantity, checked_at,
                "instrument identity mismatch",
            )
        if checked_at - observed.observed_at > policy.max_state_age:
            return PositionReconciliation(
                local.account_id, local.connection_id, local.instrument_id,
                ReconciliationStatus.STALE,
                local.quantity, observed.quantity, checked_at,
                "observed position state is stale",
            )

        difference = abs(local.quantity - observed.quantity)
        status = ReconciliationStatus.MATCHED if difference <= policy.quantity_tolerance else ReconciliationStatus.MISMATCH
        message = "position quantity reconciled" if status is ReconciliationStatus.MATCHED else "position quantity mismatch"
        return PositionReconciliation(
            local.account_id, local.connection_id, local.instrument_id,
            status, local.quantity, observed.quantity, checked_at, message,
        )


@dataclass(frozen=True, slots=True)
class ExecutionPreconditionResult:
    allowed: bool
    reasons: tuple[str, ...] = ()


class ExecutionPreconditionGate:
    """Block execution when account/position state is stale or unverifiable."""

    def evaluate(
        self,
        reconciliation: PositionReconciliation,
        *,
        require_reconciled_position: bool = True,
    ) -> ExecutionPreconditionResult:
        if not require_reconciled_position:
            return ExecutionPreconditionResult(True)
        if reconciliation.status is ReconciliationStatus.MATCHED:
            return ExecutionPreconditionResult(True)
        return ExecutionPreconditionResult(
            False,
            (f"position reconciliation status is {reconciliation.status.value}",),
        )


__all__ = [
    "ExecutionPreconditionGate",
    "ExecutionPreconditionResult",
    "PositionReconciliation",
    "PositionReconciler",
    "PositionState",
    "ReconciliationPolicy",
    "ReconciliationStatus",
]
