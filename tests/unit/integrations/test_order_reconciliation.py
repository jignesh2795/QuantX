from uuid import uuid4

import pytest

from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.reconciliation import (
    OrderObservation,
    OrderReconciler,
    OrderReconciliationStatus,
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


def test_requested_quantity_mismatch_is_explicit():
    oid = uuid4()
    local = OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "10", "0")
    broker = OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "12", "0")
    result = OrderReconciler().reconcile(local=local, broker=broker)
    assert result.status is OrderReconciliationStatus.QUANTITY_MISMATCH
    assert "requested" in result.message




def test_status_and_fill_quantity_must_be_consistent():
    oid = uuid4()

    with pytest.raises(ValueError, match="filled status"):
        OrderObservation(oid, OrderLifecycleStatus.FILLED, "10", "9")

    with pytest.raises(ValueError, match="partially filled status"):
        OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "0")

    with pytest.raises(ValueError, match="partially filled status"):
        OrderObservation(oid, OrderLifecycleStatus.PARTIALLY_FILLED, "10", "10")


def test_invalid_order_quantities_are_rejected():
    oid = uuid4()

    with pytest.raises(ValueError, match="valid decimals"):
        OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "not-a-number", "0")

    with pytest.raises(ValueError, match="positive"):
        OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "0", "0")

    with pytest.raises(ValueError, match="negative"):
        OrderObservation(oid, OrderLifecycleStatus.SUBMITTED, "10", "-1")

    with pytest.raises(ValueError, match="exceed"):
        OrderObservation(oid, OrderLifecycleStatus.FILLED, "10", "11")
