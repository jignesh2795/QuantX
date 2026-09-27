"""Canonical integration reconciliation components."""

from .account import (
    AccountFinancialState,
    AccountReconciler,
    ReconciliationFinding as AccountReconciliationFinding,
    ReconciliationReport,
    ReconciliationStatus as AccountReconciliationStatus,
    StateSource,
)
from .orders import (
    OrderObservation,
    OrderReconciliationResult,
    OrderReconciliationStatus,
    OrderReconciler,
)
from .positions import (
    PositionReconciliation,
    PositionReconciler,
    PositionState,
    ReconciliationPolicy,
    ReconciliationStatus as PositionReconciliationStatus,
)

# Keep the unqualified name as the position-reconciliation alias for existing
# callers while exposing explicit account/position names for new code.
ReconciliationStatus = PositionReconciliationStatus

__all__ = [
    "AccountFinancialState",
    "AccountReconciler",
    "AccountReconciliationFinding",
    "AccountReconciliationStatus",
    "OrderObservation",
    "OrderReconciliationResult",
    "OrderReconciliationStatus",
    "OrderReconciler",
    "PositionReconciliation",
    "PositionReconciler",
    "PositionState",
    "PositionReconciliationStatus",
    "ReconciliationPolicy",
    "ReconciliationStatus",
    "ReconciliationReport",
    "StateSource",
]
