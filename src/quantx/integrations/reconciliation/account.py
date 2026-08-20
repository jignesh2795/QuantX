"""Account-state reconciliation implementation.

This module owns account-scoped financial reconciliation. It intentionally
accepts only explicitly observed broker/paper/replay state and never creates
synthetic capital or minimum-balance assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class StateSource(StrEnum):
    BROKER = "BROKER"
    PAPER = "PAPER"
    REPLAY = "REPLAY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AccountFinancialState:
    account_id: UUID
    connection_id: UUID
    observed_at: datetime
    source: StateSource
    currency: str
    available_cash: Decimal | None = None
    equity: Decimal | None = None
    margin_used: Decimal | None = None
    margin_available: Decimal | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        for name in ("available_cash", "equity", "margin_used", "margin_available"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    field: str
    expected: str | None
    observed: str | None
    message: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    account_id: UUID
    connection_id: UUID
    status: ReconciliationStatus
    findings: tuple[ReconciliationFinding, ...] = ()


class AccountReconciler:
    """Compare local state with explicitly observed account state."""

    def compare(
        self,
        local: AccountFinancialState,
        observed: AccountFinancialState | None,
    ) -> ReconciliationReport:
        if observed is None:
            return ReconciliationReport(
                local.account_id,
                local.connection_id,
                ReconciliationStatus.UNAVAILABLE,
                (ReconciliationFinding("state", None, None, "observed account state unavailable"),),
            )
        if observed.account_id != local.account_id or observed.connection_id != local.connection_id:
            return ReconciliationReport(
                local.account_id,
                local.connection_id,
                ReconciliationStatus.MISMATCH,
                (ReconciliationFinding("identity", str(local.connection_id), str(observed.connection_id), "account/connection identity mismatch"),),
            )

        findings: list[ReconciliationFinding] = []
        for field in ("available_cash", "equity", "margin_used", "margin_available", "currency"):
            expected = getattr(local, field)
            actual = getattr(observed, field)
            if expected is not None and actual is not None and expected != actual:
                findings.append(ReconciliationFinding(field, str(expected), str(actual), f"{field} differs"))
            elif expected is not None and actual is None:
                findings.append(ReconciliationFinding(field, str(expected), None, f"{field} unavailable in observed state"))

        status = ReconciliationStatus.MATCHED if not findings else ReconciliationStatus.MISMATCH
        if any(item.observed is None for item in findings):
            status = ReconciliationStatus.INCOMPLETE
        return ReconciliationReport(local.account_id, local.connection_id, status, tuple(findings))


__all__ = [
    "AccountFinancialState",
    "AccountReconciler",
    "ReconciliationFinding",
    "ReconciliationReport",
    "ReconciliationStatus",
    "StateSource",
]
