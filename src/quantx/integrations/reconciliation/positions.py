"""Position reconciliation contracts.

This module reports observed account/position evidence. Execution readiness
decisions are owned by the canonical execution precondition evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from quantx.domain.value_objects import AccountId, BrokerConnectionId

from .account import StateSource


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class PositionState:
    account_id: AccountId
    connection_id: BrokerConnectionId
    instrument_id: str
    quantity: Decimal
    average_price: Decimal | None
    observed_at: datetime
    source: StateSource

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.source:
            raise ValueError("source must not be empty")


@dataclass(frozen=True, slots=True)
class PositionReconciliation:
    account_id: AccountId
    connection_id: BrokerConnectionId
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
        if local is None and observed is None:
            raise ValueError("at least one position state is required")
        reference = observed or local
        assert reference is not None
        if local is None or observed is None:
            return PositionReconciliation(
                reference.account_id,
                reference.connection_id,
                reference.instrument_id,
                ReconciliationStatus.INCOMPLETE,
                local.quantity if local else None,
                observed.quantity if observed else None,
                checked_at,
                "local or observed position state is missing",
            )

        if local.account_id != observed.account_id or local.connection_id != observed.connection_id:
            return PositionReconciliation(
                local.account_id,
                local.connection_id,
                local.instrument_id,
                ReconciliationStatus.MISMATCH,
                local.quantity,
                observed.quantity,
                checked_at,
                "account or connection identity mismatch",
            )
        if local.instrument_id != observed.instrument_id:
            return PositionReconciliation(
                local.account_id,
                local.connection_id,
                local.instrument_id,
                ReconciliationStatus.MISMATCH,
                local.quantity,
                observed.quantity,
                checked_at,
                "instrument identity mismatch",
            )
        if checked_at - observed.observed_at > policy.max_state_age:
            return PositionReconciliation(
                local.account_id,
                local.connection_id,
                local.instrument_id,
                ReconciliationStatus.STALE,
                local.quantity,
                observed.quantity,
                checked_at,
                "observed position state is stale",
            )

        difference = abs(local.quantity - observed.quantity)
        status = (
            ReconciliationStatus.MATCHED
            if difference <= policy.quantity_tolerance
            else ReconciliationStatus.MISMATCH
        )
        message = (
            "position quantity reconciled"
            if status is ReconciliationStatus.MATCHED
            else "position quantity mismatch"
        )
        return PositionReconciliation(
            local.account_id,
            local.connection_id,
            local.instrument_id,
            status,
            local.quantity,
            observed.quantity,
            checked_at,
            message,
        )


__all__ = [
    "PositionReconciliation",
    "PositionReconciler",
    "PositionState",
    "ReconciliationPolicy",
    "ReconciliationStatus",
]
