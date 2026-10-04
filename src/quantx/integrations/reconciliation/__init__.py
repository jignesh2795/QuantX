"""Canonical integration reconciliation components."""

from .account import (
    AccountFinancialState,
    AccountReconciler,
    ReconciliationReport,
    StateSource,
)
from .account import (
    ReconciliationFinding as AccountReconciliationFinding,
)
from .account import (
    ReconciliationStatus as AccountReconciliationStatus,
)
from .broker_evidence import BrokerOrderEvidence, BrokerOrderEvidenceStatus
from .orders import (
    OrderObservation,
    OrderReconciler,
    OrderReconciliationResult,
    OrderReconciliationStatus,
)
from .positions import (
    PositionReconciler,
    PositionReconciliation,
    PositionState,
    ReconciliationPolicy,
)
from .positions import (
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
    "BrokerOrderEvidence",
    "BrokerOrderEvidenceStatus",
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
