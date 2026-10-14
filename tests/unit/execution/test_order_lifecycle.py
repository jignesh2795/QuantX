"""Contract tests for the canonical order-status reducer."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.execution.order_lifecycle import (
    OrderLifecycle,
    OrderLifecycleEvent,
    OrderLifecycleStatus,
    OutcomeConfidence,
)


def event(
    order_id,
    status,
    *,
    order_quantity=None,
    filled_quantity=None,
    confidence=OutcomeConfidence.CONFIRMED,
):
    return OrderLifecycleEvent(
        order_id=order_id,
        status=status,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        order_quantity=order_quantity,
        filled_quantity=filled_quantity,
        confidence=confidence,
    )


def test_normal_order_lifecycle_uses_canonical_statuses_and_quantity_evidence():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.ACCEPTED))
    lifecycle.apply(
        event(
            order_id,
            OrderStatus.FILLED,
            order_quantity=Decimal("2"),
            filled_quantity=Decimal("2"),
        )
    )
    assert lifecycle.status is OrderStatus.FILLED
    assert not lifecycle.requires_reconciliation


_ALLOWED_TRANSITIONS = [
    (OrderStatus.CREATED, OrderStatus.PENDING_SUBMIT),
    (OrderStatus.CREATED, OrderStatus.SUBMITTED),
    (OrderStatus.CREATED, OrderStatus.FAILED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.ACCEPTED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.FILLED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.CANCEL_PENDING),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.CANCELLED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.REJECTED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.EXPIRED),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.UNKNOWN),
    (OrderStatus.PENDING_SUBMIT, OrderStatus.FAILED),
    (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED),
    (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.SUBMITTED, OrderStatus.FILLED),
    (OrderStatus.SUBMITTED, OrderStatus.CANCEL_PENDING),
    (OrderStatus.SUBMITTED, OrderStatus.CANCELLED),
    (OrderStatus.SUBMITTED, OrderStatus.REJECTED),
    (OrderStatus.SUBMITTED, OrderStatus.EXPIRED),
    (OrderStatus.SUBMITTED, OrderStatus.UNKNOWN),
    (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.ACCEPTED, OrderStatus.FILLED),
    (OrderStatus.ACCEPTED, OrderStatus.CANCEL_PENDING),
    (OrderStatus.ACCEPTED, OrderStatus.CANCELLED),
    (OrderStatus.ACCEPTED, OrderStatus.REJECTED),
    (OrderStatus.ACCEPTED, OrderStatus.EXPIRED),
    (OrderStatus.ACCEPTED, OrderStatus.UNKNOWN),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCEL_PENDING),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.REJECTED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.EXPIRED),
    (OrderStatus.PARTIALLY_FILLED, OrderStatus.UNKNOWN),
    (OrderStatus.CANCEL_PENDING, OrderStatus.ACCEPTED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.PARTIALLY_FILLED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.FILLED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.REJECTED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.EXPIRED),
    (OrderStatus.CANCEL_PENDING, OrderStatus.UNKNOWN),
]


@pytest.mark.parametrize(
    ("status", "order_quantity", "filled_quantity"),
    [
        (OrderStatus.CREATED, None, None),
        (OrderStatus.PENDING_SUBMIT, None, None),
        (OrderStatus.SUBMITTED, None, None),
        (OrderStatus.ACCEPTED, None, None),
        (OrderStatus.PARTIALLY_FILLED, Decimal("10"), Decimal("4")),
        (OrderStatus.CANCEL_PENDING, None, None),
    ],
)
def test_repeated_status_observations_are_idempotent(
    status,
    order_quantity,
    filled_quantity,
):
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    observation = event(
        order_id,
        status,
        order_quantity=order_quantity,
        filled_quantity=filled_quantity,
    )
    if status is not OrderStatus.CREATED:
        lifecycle.reconcile(observation)
    before = (lifecycle.status, lifecycle.filled_quantity, lifecycle.anomalies)
    lifecycle.apply(observation)
    after = (lifecycle.status, lifecycle.filled_quantity, lifecycle.anomalies)
    assert after == before


@pytest.mark.parametrize(("current_status", "next_status"), _ALLOWED_TRANSITIONS)
def test_canonical_lifecycle_all_allowed_transitions(
    current_status,
    next_status,
):
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    if current_status is not OrderStatus.CREATED:
        if current_status is OrderStatus.PARTIALLY_FILLED:
            lifecycle.reconcile(
                event(
                    order_id,
                    current_status,
                    order_quantity=Decimal("10"),
                    filled_quantity=Decimal("4"),
                )
            )
        else:
            lifecycle.reconcile(event(order_id, current_status))

    if next_status is OrderStatus.FILLED:
        next_event = event(
            order_id,
            next_status,
            order_quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
        )
    elif next_status is OrderStatus.PARTIALLY_FILLED:
        cumulative = (
            Decimal("5")
            if current_status is OrderStatus.PARTIALLY_FILLED
            else Decimal("4")
        )
        next_event = event(
            order_id,
            next_status,
            order_quantity=Decimal("10"),
            filled_quantity=cumulative,
        )
    else:
        next_event = event(order_id, next_status)

    lifecycle.apply(next_event)
    assert lifecycle.status is next_status


@pytest.mark.parametrize(
    ("status", "order_quantity", "filled_quantity"),
    [
        (OrderStatus.ACCEPTED, None, None),
        (OrderStatus.EXPIRED, None, None),
        (OrderStatus.FILLED, Decimal("2"), Decimal("2")),
    ],
)
def test_authoritative_reconciliation_accepts_first_observed_state(
    status,
    order_quantity,
    filled_quantity,
):
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.reconcile(
        event(
            order_id,
            status,
            order_quantity=order_quantity,
            filled_quantity=filled_quantity,
        )
    )
    assert lifecycle.status is status
    assert not lifecycle.requires_reconciliation


def test_authoritative_reconciliation_does_not_regress_to_submit_pending():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.reconcile(event(order_id, OrderStatus.ACCEPTED))
    with pytest.raises(ValueError, match="invalid order transition"):
        lifecycle.reconcile(event(order_id, OrderStatus.PENDING_SUBMIT))
    assert lifecycle.status is OrderStatus.ACCEPTED


def test_acknowledged_order_can_be_cancelled_directly():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.ACCEPTED))
    lifecycle.apply(event(order_id, OrderStatus.CANCELLED))
    assert lifecycle.status is OrderStatus.CANCELLED


def test_partial_fill_remainder_can_be_cancelled():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.ACCEPTED))
    lifecycle.apply(
        event(
            order_id,
            OrderStatus.PARTIALLY_FILLED,
            order_quantity=Decimal("10"),
            filled_quantity=Decimal("4"),
        )
    )
    lifecycle.apply(
        event(
            order_id,
            OrderStatus.CANCELLED,
            order_quantity=Decimal("10"),
            filled_quantity=Decimal("4"),
        )
    )
    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("4")
    assert not lifecycle.requires_reconciliation


def test_submitted_order_can_enter_cancel_pending():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.CANCEL_PENDING))
    assert lifecycle.status is OrderStatus.CANCEL_PENDING


def test_unknown_cannot_be_resolved_by_ordinary_status_observation():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.UNKNOWN, confidence=OutcomeConfidence.UNCERTAIN))
    lifecycle.apply(event(order_id, OrderStatus.ACCEPTED))
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation
    assert lifecycle.anomalies


def test_authoritative_reconciliation_resolves_unknown():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.UNKNOWN, confidence=OutcomeConfidence.UNCERTAIN))
    lifecycle.reconcile(event(order_id, OrderStatus.ACCEPTED))
    assert lifecycle.status is OrderStatus.ACCEPTED
    assert not lifecycle.requires_reconciliation


def test_acknowledged_cancel_from_unknown_does_not_resolve_unknown_evidence():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    lifecycle.apply(event(order_id, OrderStatus.UNKNOWN, confidence=OutcomeConfidence.UNCERTAIN))
    lifecycle.acknowledge_cancel(event(order_id, OrderStatus.CANCEL_PENDING))
    assert lifecycle.status is OrderStatus.CANCEL_PENDING
    assert lifecycle.requires_reconciliation
    assert lifecycle.anomalies


@pytest.mark.parametrize(
    "terminal_status",
    [
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.FAILED,
    ],
)
def test_terminal_status_is_absorbing(terminal_status):
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    if terminal_status is OrderStatus.FILLED:
        lifecycle.reconcile(
            event(
                order_id,
                terminal_status,
                order_quantity=Decimal("2"),
                filled_quantity=Decimal("2"),
            )
        )
    else:
        lifecycle.reconcile(event(order_id, terminal_status))
    contradictory = (
        OrderStatus.CANCELLED
        if terminal_status is not OrderStatus.CANCELLED
        else OrderStatus.ACCEPTED
    )
    lifecycle.apply(event(order_id, contradictory))
    assert lifecycle.status is terminal_status
    assert lifecycle.requires_reconciliation
    assert lifecycle.anomalies


def test_invalid_transition_is_rejected():
    order_id = uuid4()
    lifecycle = OrderLifecycle(order_id)
    with pytest.raises(ValueError, match="invalid order transition"):
        lifecycle.apply(
            event(
                order_id,
                OrderStatus.FILLED,
                order_quantity=Decimal("2"),
                filled_quantity=Decimal("2"),
            )
        )


def test_legacy_acknowledged_name_is_normalized_at_compatibility_boundary():
    order_id = uuid4()
    normalized = event(order_id, OrderLifecycleStatus.ACKNOWLEDGED)
    assert normalized.status is OrderStatus.ACCEPTED


def test_production_consumers_do_not_import_legacy_lifecycle_enum():
    source_root = Path(__file__).resolve().parents[3] / "src" / "quantx"
    allowed_shim = source_root / "execution" / "order_lifecycle.py"
    offenders = [
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if path != allowed_shim and "OrderLifecycleStatus" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
