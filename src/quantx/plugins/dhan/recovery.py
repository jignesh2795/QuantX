"""Read-only recovery evidence over a bound Dhan broker adapter.

This module translates Dhan broker observations into the canonical
reconciliation evidence contracts. It never submits, cancels, or replaces
orders: only the adapter's read paths (`order_detail`, `account_state`,
`position_states`) are used. Vendor SDK types never leave the transport.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from quantx.domain.execution_request import PendingExecutionRecoveryRequest
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.brokers import BrokerAdapter
from quantx.integrations.reconciliation.account import AccountFinancialState
from quantx.integrations.reconciliation.orders import OrderObservation
from quantx.integrations.reconciliation.positions import PositionState

from .adapter import DhanBrokerAdapter
from .mapping import dhan_correlation_id

_DHAN_STATUS_TO_LIFECYCLE = {
    "TRANSIT": OrderLifecycleStatus.ACKNOWLEDGED,
    "PENDING": OrderLifecycleStatus.ACKNOWLEDGED,
    "PART_TRADED": OrderLifecycleStatus.PARTIALLY_FILLED,
    "TRADED": OrderLifecycleStatus.FILLED,
    "REJECTED": OrderLifecycleStatus.REJECTED,
    "CANCELLED": OrderLifecycleStatus.CANCELLED,
}


class DhanRecoveryEvidenceProvider:
    """Reconciliation evidence bound to one Dhan account/connection/order.

    The provider is constructed for a single persisted recovery request, so
    broker evidence can never be resolved for a different account, connection,
    or order. Transport failures surface as unavailable evidence (``None``);
    identity mismatches raise fail-closed errors that keep the reservation
    pending through the existing recovery machinery.
    """

    def __init__(
        self,
        adapter: DhanBrokerAdapter,
        *,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        correlation_id: str,
        order_id: UUID,
        order_quantity: Decimal,
    ) -> None:
        if adapter.connection.account_id != account_id:
            raise ValueError("Dhan adapter account does not match recovery account")
        if adapter.connection.connection_id != connection_id:
            raise ValueError("Dhan adapter connection does not match recovery connection")
        if not correlation_id.strip():
            raise ValueError("recovery correlation id must not be empty")
        if order_quantity <= 0:
            raise ValueError("recovery order quantity must be positive")
        self._adapter = adapter
        self._account_id = account_id
        self._connection_id = connection_id
        self._correlation_id = correlation_id
        self._order_id = order_id
        self._order_quantity = order_quantity

    @property
    def account_id(self) -> AccountId:
        return self._account_id

    @property
    def connection_id(self) -> BrokerConnectionId:
        return self._connection_id

    @property
    def broker_id(self) -> str:
        return self._adapter.connection.broker_id

    def fetch_broker_order(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        order_id: UUID | None,
    ) -> OrderObservation | None:
        """Re-observe one broker order; identity mismatch fails closed."""
        self._check_scope(account_id, connection_id, order_id)
        try:
            detail = self._adapter.order_detail(
                correlation_id=dhan_correlation_id(self._correlation_id),
            )
        except Exception:
            return None
        if detail.correlation_id is not None and detail.correlation_id != dhan_correlation_id(
            self._correlation_id
        ):
            raise ValueError("Dhan order evidence correlation does not match recovery request")
        return OrderObservation(
            order_id=self._order_id,
            status=_lifecycle_status(detail.order_status),
            requested_quantity=str(self._order_quantity),
            filled_quantity=str(detail.filled_quantity),
            broker_order_id=detail.order_id,
            account_id=self._account_id,
            connection_id=self._connection_id,
        )

    def fetch_broker_position(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        instrument_id: str,
    ) -> PositionState | None:
        """Return the bound broker position for one instrument, if present."""
        self._check_scope(account_id, connection_id, self._order_id)
        for state in self._adapter.position_states():
            if str(state.instrument_id) == instrument_id:
                if state.account_id != self._account_id:
                    raise ValueError("Dhan position account does not match recovery account")
                if state.connection_id != self._connection_id:
                    raise ValueError("Dhan position connection does not match recovery connection")
                return state
        return None

    def fetch_broker_account(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
    ) -> AccountFinancialState | None:
        """Return the bound broker account snapshot; missing stays missing."""
        self._check_scope(account_id, connection_id, self._order_id)
        state = self._adapter.account_state()
        if state.account_id != self._account_id:
            raise ValueError("Dhan account does not match recovery account")
        if state.connection_id != self._connection_id:
            raise ValueError("Dhan account connection does not match recovery connection")
        return state

    def _check_scope(
        self,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        order_id: UUID | None,
    ) -> None:
        if account_id != self._account_id:
            raise ValueError("recovery evidence account does not match bound account")
        if connection_id != self._connection_id:
            raise ValueError("recovery evidence connection does not match bound connection")
        if order_id != self._order_id:
            raise ValueError("recovery evidence order does not match bound order")


def _lifecycle_status(order_status: str) -> OrderLifecycleStatus:
    """Map a raw Dhan order status onto the canonical lifecycle vocabulary.

    Unrecognized or expired broker states map to UNKNOWN rather than inventing
    a lifecycle transition; UNKNOWN evidence can never resolve recovery.
    """
    normalized = order_status.strip().upper()
    if normalized == "EXPIRED":
        return OrderLifecycleStatus.UNKNOWN
    return _DHAN_STATUS_TO_LIFECYCLE.get(normalized, OrderLifecycleStatus.UNKNOWN)


def build_dhan_recovery_provider(
    adapter: BrokerAdapter,
    request: PendingExecutionRecoveryRequest,
) -> DhanRecoveryEvidenceProvider:
    """Bind a Dhan adapter to one persisted recovery request for evidence reads.

    The application recovery boundary accepts the generic ``BrokerAdapter``
    contract. This plugin factory validates the concrete Dhan adapter at the
    plugin boundary before using Dhan-specific recovery capabilities.
    """
    if not isinstance(adapter, DhanBrokerAdapter):
        raise TypeError("Dhan recovery requires a DhanBrokerAdapter")
    context = request.execution_context
    if context.broker_connection_id is None:
        raise ValueError("pending recovery requires a broker connection identity")
    return DhanRecoveryEvidenceProvider(
        adapter,
        account_id=context.account_id,
        connection_id=context.broker_connection_id,
        correlation_id=request.correlation_id,
        order_id=request.order.client_order_id,
        order_quantity=request.order.quantity,
    )


__all__ = [
    "DhanRecoveryEvidenceProvider",
    "build_dhan_recovery_provider",
]
