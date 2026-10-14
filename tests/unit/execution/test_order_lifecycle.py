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
    lifecycle.apply(event(order_id, OrderStatus.SUBMITTED))
    if terminal_status is OrderStatus.FILLED:
        lifecycle.apply(
            event(
                order_id,
                terminal_status,
                order_quantity=Decimal("2"),
                filled_quantity=Decimal("2"),
            )
        )
    else:
        lifecycle.apply(event(order_id, terminal_status))
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
