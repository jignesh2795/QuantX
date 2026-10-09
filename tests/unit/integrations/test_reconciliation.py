from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.preconditions.evaluator import execution_ready_from_evidence
from quantx.integrations.reconciliation import (
    PositionReconciler,
    PositionState,
    ReconciliationPolicy,
    ReconciliationStatus,
    StateSource,
)


def test_matching_position_is_executable() -> None:
    account = AccountId("acct-1")
    connection = BrokerConnectionId("conn-1")
    now = datetime.now(timezone.utc)
    state = PositionState(
        account, connection, "BTC", Decimal("1"), Decimal("100"), now, StateSource.BROKER
    )
    result = PositionReconciler().reconcile(
        state,
        state,
        checked_at=now,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.MATCHED
    precondition = execution_ready_from_evidence(
        account_state_status="PAPER",
        position_state_status=result.status.value,
        connection_health="HEALTHY",
        required_capabilities_ok=True,
    )
    assert precondition.can_execute


def test_stale_observed_position_blocks_execution() -> None:
    account = AccountId("acct-1")
    connection = BrokerConnectionId("conn-1")
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    checked_at = datetime.now(timezone.utc)
    local = PositionState(
        account, connection, "BTC", Decimal("1"), None, checked_at, StateSource.PAPER
    )
    observed = PositionState(
        account, connection, "BTC", Decimal("1"), None, observed_at, StateSource.BROKER
    )
    result = PositionReconciler().reconcile(
        local,
        observed,
        checked_at=checked_at,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.STALE
    precondition = execution_ready_from_evidence(
        account_state_status="PAPER",
        position_state_status=result.status.value,
        connection_health="HEALTHY",
        required_capabilities_ok=True,
    )
    assert not precondition.can_execute


def test_missing_observed_position_is_incomplete_and_blocks() -> None:
    account = AccountId("acct-1")
    connection = BrokerConnectionId("conn-1")
    now = datetime.now(timezone.utc)
    local = PositionState(account, connection, "BTC", Decimal("1"), None, now, StateSource.PAPER)
    result = PositionReconciler().reconcile(
        local,
        None,
        checked_at=now,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.INCOMPLETE
    precondition = execution_ready_from_evidence(
        account_state_status="PAPER",
        position_state_status=result.status.value,
        connection_health="HEALTHY",
        required_capabilities_ok=True,
    )
    assert not precondition.can_execute
