from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from quantx.integrations.reconciliation import (
    ExecutionPreconditionGate,
    PositionReconciler,
    PositionState,
    ReconciliationPolicy,
    ReconciliationStatus,
)


def test_matching_position_is_executable() -> None:
    account = uuid4()
    connection = uuid4()
    now = datetime.now(timezone.utc)
    state = PositionState(account, connection, "BTC", Decimal("1"), Decimal("100"), now, "broker")
    result = PositionReconciler().reconcile(
        state,
        state,
        checked_at=now,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert ExecutionPreconditionGate().evaluate(result).allowed


def test_stale_observed_position_blocks_execution() -> None:
    account = uuid4()
    connection = uuid4()
    observed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    checked_at = datetime.now(timezone.utc)
    local = PositionState(account, connection, "BTC", Decimal("1"), None, checked_at, "local")
    observed = PositionState(account, connection, "BTC", Decimal("1"), None, observed_at, "broker")
    result = PositionReconciler().reconcile(
        local,
        observed,
        checked_at=checked_at,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.STALE
    assert not ExecutionPreconditionGate().evaluate(result).allowed


def test_missing_observed_position_is_incomplete_and_blocks() -> None:
    account = uuid4()
    connection = uuid4()
    now = datetime.now(timezone.utc)
    local = PositionState(account, connection, "BTC", Decimal("1"), None, now, "local")
    result = PositionReconciler().reconcile(
        local,
        None,
        checked_at=now,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.INCOMPLETE
    assert not ExecutionPreconditionGate().evaluate(result).allowed
