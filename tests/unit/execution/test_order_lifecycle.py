from datetime import datetime, timezone
from uuid import uuid4

import pytest

from quantx.execution.order_lifecycle import (
    OrderLifecycle,
    OrderLifecycleEvent,
    OrderLifecycleStatus,
    OutcomeConfidence,
)


def event(order_id, status, confidence=OutcomeConfidence.CONFIRMED):
    return OrderLifecycleEvent(
        order_id=order_id,
        status=status,
        observed_at=datetime.now(timezone.utc),
        source="test",
        confidence=confidence,
    )


def test_normal_order_lifecycle_reaches_filled():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderLifecycleStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderLifecycleStatus.ACKNOWLEDGED))
    lifecycle.apply(event(order_id, OrderLifecycleStatus.FILLED))
    assert lifecycle.status is OrderLifecycleStatus.FILLED


def test_uncertain_submission_outcome_enters_unknown():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderLifecycleStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderLifecycleStatus.UNKNOWN, OutcomeConfidence.UNCERTAIN))
    assert lifecycle.status is OrderLifecycleStatus.UNKNOWN


def test_invalid_transition_is_rejected():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    with pytest.raises(ValueError):
        lifecycle.apply(event(order_id, OrderLifecycleStatus.FILLED))
