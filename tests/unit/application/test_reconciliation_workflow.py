"""Deterministic offline tests for the order-state reconciliation workflow."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.application.reconciliation import (
    OrderStateReconciliationWorkflow,
    OrderWorkflowStatus,
)
from quantx.domain.enums import OrderStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    ReconciliationPolicy,
    StateSource,
)

CHECKED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
POLICY = ReconciliationPolicy(timedelta(seconds=30))


def _receipt(
    order_id: UUID,
    *,
    broker_order_id: str | None = "dhan-1",
    account_id: AccountId | None = None,
    connection_id: BrokerConnectionId | None = None,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=CHECKED_AT,
        broker_order_id=broker_order_id,
        order_id=order_id,
        account_id=account_id or AccountId("acct-1"),
        connection_id=connection_id or BrokerConnectionId("conn-1"),
    )


def _observation(
    order_id: UUID,
    status: OrderLifecycleStatus = OrderLifecycleStatus.FILLED,
    *,
    filled: str = "2",
    broker_order_id: str | None = "dhan-1",
) -> OrderObservation:
    return OrderObservation(order_id, status, "2", filled, broker_order_id)


def _position(
    quantity: Decimal = Decimal("10"),
    *,
    observed_at: datetime = CHECKED_AT,
    source: StateSource = StateSource.PAPER,
) -> PositionState:
    return PositionState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "NSE:TCS",
        quantity,
        Decimal("100"),
        observed_at,
        source,
    )


def _account(
    *,
    available_cash: Decimal | None = Decimal("5000"),
    source: StateSource = StateSource.PAPER,
) -> AccountFinancialState:
    return AccountFinancialState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        CHECKED_AT,
        source,
        "INR",
        available_cash=available_cash,
        margin_used=Decimal("0"),
    )


def _workflow() -> OrderStateReconciliationWorkflow:
    return OrderStateReconciliationWorkflow()


def test_matched_order_is_definitive_matched() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MATCHED
    assert result.definitive is True
    assert result.order_id == order_id
    assert result.broker_order_id == "dhan-1"


def test_missing_broker_order_is_incomplete() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=None,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.INCOMPLETE
    assert result.definitive is False


def test_missing_local_order_is_incomplete() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=None,
        broker_order=_observation(order_id),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.INCOMPLETE
    assert result.definitive is False


def test_state_mismatch_is_mismatch() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id, OrderLifecycleStatus.FILLED),
        broker_order=_observation(order_id, OrderLifecycleStatus.REJECTED),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MISMATCH
    assert result.definitive is False


def test_quantity_mismatch_is_mismatch() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id, filled="2"),
        broker_order=_observation(order_id, filled="1"),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MISMATCH
    assert result.definitive is False


def test_unknown_order_evidence_never_becomes_definitive() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.UNKNOWN
    assert result.definitive is False
    assert "FILLED" not in result.status.value
    assert "REJECTED" not in result.status.value


def test_unknown_order_with_matched_downstream_stays_unknown() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        local_position=_position(),
        broker_position=_position(source=StateSource.BROKER),
        local_account=_account(),
        broker_account=_account(source=StateSource.BROKER),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.UNKNOWN
    assert result.definitive is False


def test_matched_order_with_stale_position_is_incomplete() -> None:
    order_id = uuid4()
    stale = _position(
        observed_at=CHECKED_AT - timedelta(minutes=5),
        source=StateSource.BROKER,
    )

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        local_position=_position(),
        broker_position=stale,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.INCOMPLETE
    assert result.definitive is False


def test_matched_order_with_incomplete_position_is_incomplete() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        local_position=_position(),
        broker_position=None,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.INCOMPLETE
    assert result.definitive is False


def test_matched_order_with_unavailable_account_is_incomplete() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        local_account=_account(),
        broker_account=None,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.INCOMPLETE
    assert result.definitive is False


def test_fully_matched_evidence_is_definitive_matched() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        local_position=_position(),
        broker_position=_position(source=StateSource.BROKER),
        local_account=_account(),
        broker_account=_account(source=StateSource.BROKER),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MATCHED
    assert result.definitive is True
    assert result.account_id == AccountId("acct-1")
    assert result.connection_id == BrokerConnectionId("conn-1")


def test_evidence_for_another_account_is_mismatch() -> None:
    order_id = uuid4()
    foreign = PositionState(
        AccountId("acct-2"),
        BrokerConnectionId("conn-1"),
        "NSE:TCS",
        Decimal("10"),
        Decimal("100"),
        CHECKED_AT,
        StateSource.BROKER,
    )

    result = _workflow().reconcile(
        _receipt(order_id),
        local_order=_observation(order_id),
        broker_order=_observation(order_id),
        local_position=_position(),
        broker_position=foreign,
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MISMATCH
    assert result.definitive is False


def test_broker_order_id_binding_mismatch_is_mismatch() -> None:
    order_id = uuid4()

    result = _workflow().reconcile(
        _receipt(order_id, broker_order_id="dhan-1"),
        local_order=_observation(order_id, broker_order_id="dhan-1"),
        broker_order=_observation(order_id, broker_order_id="dhan-2"),
        checked_at=CHECKED_AT,
    )

    assert result.status is OrderWorkflowStatus.MISMATCH
    assert result.definitive is False
