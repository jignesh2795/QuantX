"""Deterministic refresh of unresolved reconciliation evidence.

The canonical reconcilers stay pure comparison components and the order-state
workflow stays the single place where evidence becomes a normalized result.
This application-layer coordinator re-observes broker evidence through an
explicit provider seam and re-runs the workflow. Definitive outcomes require
explicitly required evidence; UNKNOWN can never become definitive without it.
No sleeps, threads, timers, background jobs, or network behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.reconciliation.account import AccountFinancialState
from quantx.integrations.reconciliation.orders import OrderObservation
from quantx.integrations.reconciliation.positions import (
    PositionState,
    ReconciliationPolicy,
)

from .reconciliation import (
    OrderStateReconciliationResult,
    OrderStateReconciliationWorkflow,
    OrderWorkflowStatus,
)


class ReconciliationEvidenceProvider(Protocol):
    """Explicit seam for re-observing broker evidence, offline-testable."""

    def fetch_broker_order(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        order_id: UUID | None,
    ) -> OrderObservation | None: ...

    def fetch_broker_position(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        instrument_id: str,
    ) -> PositionState | None: ...

    def fetch_broker_account(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
    ) -> AccountFinancialState | None: ...


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Explicit budget for evidence refresh attempts."""

    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True, slots=True)
class DefinitiveEvidencePolicy:
    """Which evidence domains must match for a definitive reconciliation.

    The default is conservative: order, position, and account evidence must
    all be definitively matched. Narrower workflows opt out explicitly.
    """

    require_position: bool = True
    require_account: bool = True

    @classmethod
    def all_required(cls) -> DefinitiveEvidencePolicy:
        return cls(require_position=True, require_account=True)

    @classmethod
    def order_and_position(cls) -> DefinitiveEvidencePolicy:
        return cls(require_position=True, require_account=False)

    @classmethod
    def order_only(cls) -> DefinitiveEvidencePolicy:
        return cls(require_position=False, require_account=False)


@dataclass(frozen=True, slots=True)
class EvidenceRefreshOutcome:
    """Latest canonical result plus the refresh trail that produced it."""

    result: OrderStateReconciliationResult
    attempts: int
    refreshed_domains: tuple[str, ...]
    definitive: bool
    reasons: tuple[str, ...] = ()
    broker_order: OrderObservation | None = None
    broker_position: PositionState | None = None
    broker_account: AccountFinancialState | None = None


class ReconciliationEvidenceRefresher:
    """Refresh unresolved evidence and re-run the canonical workflow.

    Only refreshable uncertainty (UNKNOWN, missing, stale, incomplete,
    unavailable evidence) is re-observed. Definitive mismatches are never
    retried into a different interpretation, and an exhausted budget leaves
    the last unresolved result non-definitive.
    """

    def __init__(
        self,
        *,
        workflow: OrderStateReconciliationWorkflow | None = None,
        refresh_policy: RefreshPolicy | None = None,
        evidence_policy: DefinitiveEvidencePolicy | None = None,
    ) -> None:
        self._workflow = workflow or OrderStateReconciliationWorkflow()
        self._refresh = refresh_policy or RefreshPolicy()
        self._evidence = evidence_policy or DefinitiveEvidencePolicy.all_required()

    def refresh(
        self,
        receipt: ExecutionReceipt,
        *,
        local_order: OrderObservation | None,
        broker_order: OrderObservation | None,
        local_position: PositionState | None = None,
        broker_position: PositionState | None = None,
        local_account: AccountFinancialState | None = None,
        broker_account: AccountFinancialState | None = None,
        checked_at: datetime,
        position_policy: ReconciliationPolicy | None = None,
        provider: ReconciliationEvidenceProvider,
    ) -> EvidenceRefreshOutcome:
        policy = position_policy or ReconciliationPolicy(timedelta(seconds=30))
        refreshed: list[str] = []
        attempts = 0
        current_broker_order = broker_order
        current_broker_position = broker_position
        current_broker_account = broker_account

        while True:
            result = self._workflow.reconcile(
                receipt,
                local_order=local_order,
                broker_order=current_broker_order,
                local_position=local_position,
                broker_position=current_broker_position,
                local_account=local_account,
                broker_account=current_broker_account,
                checked_at=checked_at,
                position_policy=policy,
            )
            if self._is_definitive(result):
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    True,
                    (),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                )
            if self._is_definitive_mismatch(result):
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    ("definitive mismatch; evidence not refreshed",),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                )
            if attempts >= self._refresh.max_attempts:
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    ("refresh budget exhausted; last unresolved evidence preserved",),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                )
            targets = self._refresh_targets(result)
            if not targets:
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    ("no refreshable evidence",),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                )
            for domain in targets:
                fetched_any = False
                if domain == "order":
                    fetched = provider.fetch_broker_order(
                        account_id=receipt.account_id,
                        connection_id=receipt.connection_id,
                        order_id=result.order_id,
                    )
                    fetched_any = True
                    if fetched is not None:
                        current_broker_order = fetched
                elif domain == "position":
                    instrument_id = self._position_instrument(
                        local_position, current_broker_position
                    )
                    if instrument_id is not None:
                        fetched_position = provider.fetch_broker_position(
                            account_id=receipt.account_id,
                            connection_id=receipt.connection_id,
                            instrument_id=instrument_id,
                        )
                        fetched_any = True
                        if fetched_position is not None:
                            current_broker_position = fetched_position
                elif domain == "account":
                    fetched_account = provider.fetch_broker_account(
                        account_id=receipt.account_id,
                        connection_id=receipt.connection_id,
                    )
                    fetched_any = True
                    if fetched_account is not None:
                        current_broker_account = fetched_account
                if fetched_any and domain not in refreshed:
                    refreshed.append(domain)
            attempts += 1

    def _is_definitive(self, result: OrderStateReconciliationResult) -> bool:
        if result.status is not OrderWorkflowStatus.MATCHED:
            return False
        if self._evidence.require_position and (
            result.position is None or result.position.status.value != "MATCHED"
        ):
            return False
        if self._evidence.require_account and (
            result.account is None or result.account.status.value != "MATCHED"
        ):
            return False
        return True

    @staticmethod
    def _is_definitive_mismatch(result: OrderStateReconciliationResult) -> bool:
        return result.status is OrderWorkflowStatus.MISMATCH

    def _refresh_targets(self, result: OrderStateReconciliationResult) -> tuple[str, ...]:
        targets: list[str] = []
        if result.order is not None and result.order.status.value != "MATCHED":
            targets.append("order")
        if self._evidence.require_position and (
            result.position is None or result.position.status.value != "MATCHED"
        ):
            targets.append("position")
        if self._evidence.require_account and (
            result.account is None or result.account.status.value != "MATCHED"
        ):
            targets.append("account")
        return tuple(targets)

    @staticmethod
    def _position_instrument(
        local_position: PositionState | None,
        broker_position: PositionState | None,
    ) -> str | None:
        if local_position is not None:
            return local_position.instrument_id
        if broker_position is not None:
            return broker_position.instrument_id
        return None
