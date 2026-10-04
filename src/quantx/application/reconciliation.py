"""Order-state reconciliation workflow over canonical evidence.

The workflow orchestrates the existing canonical reconcilers without
duplicating them: it takes a local execution receipt plus broker/local
observations, invokes reconciliation, and propagates evidence without losing
uncertainty. UNKNOWN evidence is never converted into a definitive outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.reconciliation.account import (
    AccountFinancialState,
    AccountReconciler,
    ReconciliationReport,
)
from quantx.integrations.reconciliation.account import (
    ReconciliationFinding as AccountReconciliationFinding,
)
from quantx.integrations.reconciliation.account import (
    ReconciliationStatus as AccountReconciliationStatus,
)
from quantx.integrations.reconciliation.orders import (
    OrderObservation,
    OrderReconciler,
    OrderReconciliationResult,
    OrderReconciliationStatus,
)
from quantx.integrations.reconciliation.positions import (
    PositionReconciler,
    PositionReconciliation,
    PositionState,
    ReconciliationPolicy,
)


class OrderWorkflowStatus(StrEnum):
    """Conservative aggregate over canonical reconciliation evidence."""

    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class OrderStateReconciliationResult:
    """Normalized workflow outcome preserving canonical evidence."""

    order_id: UUID | None
    account_id: AccountId | None
    connection_id: BrokerConnectionId | None
    broker_order_id: str | None
    order: OrderReconciliationResult | None
    position: PositionReconciliation | None
    account: ReconciliationReport | None
    status: OrderWorkflowStatus
    reasons: tuple[str, ...] = ()
    identity_error: str | None = None

    @property
    def definitive(self) -> bool:
        return self.status is OrderWorkflowStatus.MATCHED


class OrderStateReconciliationWorkflow:
    """Reconcile one execution result against broker observations.

    The reconcilers remain pure comparison components; this workflow only
    supplies evidence, checks identity bindings, and aggregates statuses
    conservatively: any UNKNOWN evidence blocks a definitive outcome, and
    missing, stale, incomplete, or unavailable evidence stays non-definitive.
    """

    def __init__(
        self,
        *,
        order_reconciler: OrderReconciler | None = None,
        position_reconciler: PositionReconciler | None = None,
        account_reconciler: AccountReconciler | None = None,
    ) -> None:
        self._orders = order_reconciler or OrderReconciler()
        self._positions = position_reconciler or PositionReconciler()
        self._accounts = account_reconciler or AccountReconciler()

    def reconcile(
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
        require_order_scope: bool = False,
    ) -> OrderStateReconciliationResult:
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        policy = position_policy or ReconciliationPolicy(timedelta(seconds=30))

        order_id = self._resolve_order_id(receipt, local_order, broker_order)
        reasons: list[str] = []

        identity_reason = self._check_identity(
            receipt,
            local_order,
            broker_order,
            local_position,
            broker_position,
            local_account,
            broker_account,
            require_order_scope=require_order_scope,
        )

        order = self._reconcile_order(local_order, broker_order, order_id)
        position = self._reconcile_position(local_position, broker_position, checked_at, policy)
        account = self._reconcile_account(
            local_account,
            broker_account,
            checked_at=checked_at,
            max_state_age=policy.max_state_age,
        )

        if identity_reason is not None:
            reasons.append(identity_reason)
        if order is not None and order.status is not OrderReconciliationStatus.MATCHED:
            reasons.append(f"order: {order.message}")
        if position is not None and position.status.value != "MATCHED":
            reasons.append(f"position: {position.message}")
        if account is not None and account.status.value != "MATCHED":
            detail = account.findings[0].message if account.findings else account.status.value
            reasons.append(f"account: {detail}")

        status = self._aggregate(order, position, account)
        if identity_reason is not None:
            status = OrderWorkflowStatus.MISMATCH

        return OrderStateReconciliationResult(
            order_id=order_id,
            account_id=receipt.account_id,
            connection_id=receipt.connection_id,
            broker_order_id=receipt.broker_order_id,
            order=order,
            position=position,
            account=account,
            status=status,
            reasons=tuple(reasons),
            identity_error=identity_reason,
        )

    @staticmethod
    def _resolve_order_id(
        receipt: ExecutionReceipt,
        local_order: OrderObservation | None,
        broker_order: OrderObservation | None,
    ) -> UUID | None:
        if local_order is not None:
            return local_order.order_id
        if broker_order is not None:
            return broker_order.order_id
        return receipt.order_id

    @staticmethod
    def _check_identity(
        receipt: ExecutionReceipt,
        local_order: OrderObservation | None,
        broker_order: OrderObservation | None,
        local_position: PositionState | None,
        broker_position: PositionState | None,
        local_account: AccountFinancialState | None,
        broker_account: AccountFinancialState | None,
        *,
        require_order_scope: bool = False,
    ) -> str | None:
        if (
            receipt.broker_order_id is not None
            and broker_order is not None
            and broker_order.broker_order_id is not None
            and broker_order.broker_order_id != receipt.broker_order_id
        ):
            return "broker order identity does not match execution receipt"
        for state in (local_position, broker_position, local_account, broker_account):
            if state is None:
                continue
            if receipt.account_id is not None and state.account_id != receipt.account_id:
                return "evidence account does not match execution receipt account"
            if receipt.connection_id is not None and state.connection_id != receipt.connection_id:
                return "evidence connection does not match execution receipt connection"
        if require_order_scope and broker_order is not None:
            if broker_order.account_id is None or broker_order.connection_id is None:
                return "broker order evidence lacks account/connection binding"
            if receipt.account_id is not None and broker_order.account_id != receipt.account_id:
                return "broker order evidence account does not match execution receipt account"
            if (
                receipt.connection_id is not None
                and broker_order.connection_id != receipt.connection_id
            ):
                return (
                    "broker order evidence connection does not match "
                    "execution receipt connection"
                )

        if (
            local_order is not None
            and receipt.broker_order_id is not None
            and local_order.broker_order_id is not None
            and local_order.broker_order_id != receipt.broker_order_id
        ):
            return "local order broker identity does not match execution receipt"
        if (
            local_order is not None
            and broker_order is not None
            and local_order.broker_order_id is not None
            and broker_order.broker_order_id is not None
            and local_order.broker_order_id != broker_order.broker_order_id
        ):
            return "local and broker broker-order identity does not match"
        if (
            local_order is not None
            and broker_order is not None
            and local_order.order_id != broker_order.order_id
        ):
            return "local and broker order identity does not match"
        return None

    def _reconcile_order(
        self,
        local_order: OrderObservation | None,
        broker_order: OrderObservation | None,
        order_id: UUID | None,
    ) -> OrderReconciliationResult | None:
        if local_order is None and broker_order is None:
            if order_id is None:
                raise ValueError("order identity is required for reconciliation")
            return OrderReconciliationResult(
                order_id,
                OrderReconciliationStatus.UNKNOWN,
                "no local or broker order observation",
            )
        if (
            local_order is not None
            and broker_order is not None
            and local_order.order_id != broker_order.order_id
        ):
            return OrderReconciliationResult(
                local_order.order_id,
                OrderReconciliationStatus.STATE_MISMATCH,
                "local and broker order identity does not match",
            )
        return self._orders.reconcile(local=local_order, broker=broker_order)

    def _reconcile_position(
        self,
        local_position: PositionState | None,
        broker_position: PositionState | None,
        checked_at: datetime,
        policy: ReconciliationPolicy,
    ) -> PositionReconciliation | None:
        if local_position is None and broker_position is None:
            return None
        return self._positions.reconcile(
            local_position,
            broker_position,
            checked_at=checked_at,
            policy=policy,
        )

    def _reconcile_account(
        self,
        local_account: AccountFinancialState | None,
        broker_account: AccountFinancialState | None,
        *,
        checked_at: datetime,
        max_state_age: timedelta,
    ) -> ReconciliationReport | None:
        if local_account is None and broker_account is None:
            return None
        if local_account is None:
            assert broker_account is not None
            return ReconciliationReport(
                broker_account.account_id,
                broker_account.connection_id,
                AccountReconciliationStatus.INCOMPLETE,
                (
                    AccountReconciliationFinding(
                        "state",
                        None,
                        None,
                        "local account state missing",
                    ),
                ),
            )
        return self._accounts.compare(
            local_account,
            broker_account,
            checked_at=checked_at,
            max_state_age=max_state_age,
        )

    @staticmethod
    def _aggregate(
        order: OrderReconciliationResult | None,
        position: PositionReconciliation | None,
        account: ReconciliationReport | None,
    ) -> OrderWorkflowStatus:
        if order is None or order.status is OrderReconciliationStatus.UNKNOWN:
            return OrderWorkflowStatus.UNKNOWN
        if order.status in {
            OrderReconciliationStatus.MISSING_BROKER_ORDER,
            OrderReconciliationStatus.MISSING_LOCAL_ORDER,
        }:
            return OrderWorkflowStatus.INCOMPLETE
        if order.status is not OrderReconciliationStatus.MATCHED:
            return OrderWorkflowStatus.MISMATCH
        # Downstream statuses come from distinct position/account enums, so
        # compare by value rather than enum identity.
        for downstream in (position, account):
            if downstream is None:
                continue
            if downstream.status.value == "MISMATCH":
                return OrderWorkflowStatus.MISMATCH
            if downstream.status.value != "MATCHED":
                return OrderWorkflowStatus.INCOMPLETE
        return OrderWorkflowStatus.MATCHED
