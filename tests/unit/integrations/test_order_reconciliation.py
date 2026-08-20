from uuid import uuid4

from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.order_reconciliation import (
    OrderObservation,
    OrderReconciliationStatus,
    OrderReconciler,
)


def test_matching_order_observation_is_reconciled():
    oid = uuid4()
    local = OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "4", "broker-1")
    broker = OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "4", "broker-1")
    result = OrderReconciler().reconcile(local=local, broker=broker)
    assert result.status is OrderReconciliationStatus.MATCHED


def test_unknown_broker_order_blocks_assumption_of_success():
    oid = uuid4()
    local = OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "10", "0")
    result = OrderReconciler().reconcile(local=local, broker=None)
    assert result.status is OrderReconciliationStatus.MISSING_BROKER_ORDER


def test_quantity_mismatch_is_explicit():
    oid = uuid4()
    local = OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "4")
    broker = OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "6")
    result = OrderReconciler().reconcile(local=local, broker=broker)
    assert result.status is OrderReconciliationStatus.QUANTITY_MISMATCH
