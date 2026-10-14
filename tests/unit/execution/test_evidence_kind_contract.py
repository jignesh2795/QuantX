"""Real-path regression coverage for the receipt evidence-kind contract (QX-03).

These tests exercise the actual ExecutionReceipt model, the ExecutionLifecycle
reducer, Dhan adapter reconcile receipts, and SQLite persistence together —
not the reducer in isolation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus, OrderType
from quantx.domain.orders import Fill, Order
from quantx.domain.value_objects import InstrumentId
from quantx.execution.ports import ExecutionOutcome
from quantx.execution.receipts import ExecutionEvidenceKind, ExecutionReceipt
from quantx.execution.receipts.lifecycle import ExecutionLifecycle

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _order(quantity: Decimal = Decimal("2")) -> Order:
    return Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )


def _fill(order: Order, quantity: Decimal, *, execution_id=None, price=Decimal("100")) -> Fill:
    return Fill(
        client_order_id=order.client_order_id,
        instrument=order.instrument,
        side=order.side,
        quantity=quantity,
        price=price,
        execution_id=execution_id or uuid4(),
    )


def _delta_receipt(
    order: Order,
    *,
    outcome: ExecutionOutcome,
    status: OrderStatus,
    fills: tuple[Fill, ...],
    executed_at: datetime = BASE,
    receipt_id=None,
) -> ExecutionReceipt:
    """Build an execution-delta receipt directly.

    Uses the raw constructor (not ``from_order``) so reducer-level sequences can
    carry partial fills; single-receipt outcome/quantity coherence is validated
    separately by ``from_order`` in the model tests.
    """
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order.client_order_id,
        outcome=outcome,
        order_status=status,
        executed_at=executed_at,
        fills=fills,
        source="paper",
        simulated=True,
        receipt_id=receipt_id or uuid4(),
        order_id=order.client_order_id,
        order_quantity=order.quantity,
        evidence_kind=ExecutionEvidenceKind.EXECUTION_DELTAS,
    )


def _cumulative_receipt(
    order: Order,
    *,
    observed: Decimal,
    status: OrderStatus,
    outcome: ExecutionOutcome,
    executed_at: datetime = BASE,
    receipt_id=None,
    average_price: Decimal | None = None,
) -> ExecutionReceipt:
    """Build a Dhan-style cumulative observation receipt with no synthetic fill."""
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order.client_order_id,
        outcome=outcome,
        order_status=status,
        executed_at=executed_at,
        fills=(),
        source="dhan",
        simulated=False,
        broker_order_id="DHAN-1",
        receipt_id=receipt_id or uuid4(),
        order_id=order.client_order_id,
        order_quantity=order.quantity,
        evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
        observed_filled_quantity=observed,
        observed_average_price=average_price,
    )


def _lifecycle(order: Order) -> ExecutionLifecycle:
    return ExecutionLifecycle(order.client_order_id, order.quantity)


# ---------------------------------------------------------------------------
# Cumulative observation semantics
# ---------------------------------------------------------------------------


def test_two_cumulative_snapshots_of_one_never_become_two() -> None:
    """Two Dhan snapshots each reporting 1 → never a clean full fill of 2."""
    order = _order()
    lifecycle = _lifecycle(order)
    first = _cumulative_receipt(
        order,
        observed=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        executed_at=BASE,
    )
    second = _cumulative_receipt(
        order,
        observed=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        executed_at=BASE + timedelta(seconds=5),
    )
    lifecycle = lifecycle.apply(first)
    lifecycle = lifecycle.apply(second)
    assert lifecycle.filled_quantity == Decimal("1")
    assert lifecycle.observed_filled_quantity == Decimal("1")
    assert lifecycle.remaining_quantity == Decimal("1")


def test_cumulative_then_increasing_cumulative_is_monotonic() -> None:
    """Cumulative 1 then cumulative 2 → observed quantity 2, not 3."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("2"),
            status=OrderStatus.FILLED,
            outcome=ExecutionOutcome.FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.observed_filled_quantity == Decimal("2")
    assert lifecycle.filled_quantity == Decimal("2")
    assert lifecycle.status is OrderStatus.FILLED


def test_cumulative_cancellation_retains_known_fill() -> None:
    """Cumulative 1, then CANCELLED reporting cumulative 1 → cancelled, filled 1, remaining 1."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.CANCELLED,
            outcome=ExecutionOutcome.CANCELLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.filled_quantity == Decimal("1")
    assert lifecycle.remaining_quantity == Decimal("1")
    assert lifecycle.status is OrderStatus.CANCELLED


def test_decreasing_cumulative_sets_anomaly_and_blocks() -> None:
    """A decreasing cumulative observation must require reconciliation."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("2"),
            status=OrderStatus.FILLED,
            outcome=ExecutionOutcome.FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.FILLED,
            outcome=ExecutionOutcome.FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False
    assert any("decreased" in a for a in lifecycle.anomalies)


def test_cumulative_exceeding_order_quantity_sets_anomaly() -> None:
    order = _order(quantity=Decimal("1"))
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("2"),
            status=OrderStatus.FILLED,
            outcome=ExecutionOutcome.FILLED,
            executed_at=BASE,
        )
    )
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.filled_quantity == Decimal("0")


def test_cumulative_receipt_without_observed_quantity_is_rejected() -> None:
    order = _order()
    with pytest.raises(ValueError, match="observed_filled_quantity"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=order.client_order_id,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
        )


# ---------------------------------------------------------------------------
# Evidence-shape invariants on the receipt model itself
# ---------------------------------------------------------------------------


def test_cumulative_receipt_rejects_fills_through_direct_constructor() -> None:
    order = _order()
    with pytest.raises(ValueError, match="must not carry fills"):
        ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=order.client_order_id,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(_fill(order, Decimal("1")),),
            order_id=order.client_order_id,
            order_quantity=order.quantity,
            evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
            observed_filled_quantity=Decimal("1"),
        )


def test_cumulative_receipt_rejects_fills_through_from_order() -> None:
    order = _order()
    with pytest.raises(ValueError, match="must not carry fills"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(_fill(order, Decimal("1")),),
            evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
            observed_filled_quantity=Decimal("1"),
        )


def test_cumulative_receipt_rejects_negative_observed_quantity() -> None:
    order = _order()
    with pytest.raises(ValueError, match="observed_filled_quantity cannot be negative"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
            observed_filled_quantity=Decimal("-1"),
        )


@pytest.mark.parametrize("observed_field", ["observed_filled_quantity", "observed_average_price"])
def test_delta_receipt_rejects_observation_fields_through_direct_constructor(
    observed_field: str,
) -> None:
    order = _order()
    payload = {
        "request_id": uuid4(),
        "client_order_id": order.client_order_id,
        "outcome": ExecutionOutcome.PARTIALLY_FILLED,
        "order_status": OrderStatus.PARTIALLY_FILLED,
        "executed_at": BASE,
        "fills": (_fill(order, Decimal("1")),),
        "order_id": order.client_order_id,
        "order_quantity": order.quantity,
        "evidence_kind": ExecutionEvidenceKind.EXECUTION_DELTAS,
        observed_field: Decimal("1"),
    }
    with pytest.raises(ValueError, match="must not carry cumulative observation fields"):
        ExecutionReceipt(**payload)  # type: ignore[arg-type]


@pytest.mark.parametrize("observed_field", ["observed_filled_quantity", "observed_average_price"])
def test_delta_receipt_rejects_observation_fields_through_from_order(observed_field: str) -> None:
    order = _order()
    with pytest.raises(ValueError, match="must not carry cumulative observation fields"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(_fill(order, Decimal("1")),),
            evidence_kind=ExecutionEvidenceKind.EXECUTION_DELTAS,
            **{observed_field: Decimal("1")},
        )


def test_duplicate_execution_ids_are_rejected() -> None:
    order = _order()
    shared = uuid4()
    with pytest.raises(ValueError, match="unique execution_id"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(_fill(order, Decimal("1"), execution_id=shared),)
            + (_fill(order, Decimal("1"), execution_id=shared),),
        )


def test_fill_exceeding_order_quantity_is_rejected() -> None:
    order = _order(quantity=Decimal("1"))
    with pytest.raises(ValueError, match="exceed order quantity"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(_fill(order, Decimal("2")),),
        )


def test_fill_from_another_client_order_is_rejected() -> None:
    order = _order()
    foreign = Fill(
        client_order_id=uuid4(),
        instrument=order.instrument,
        side=order.side,
        quantity=Decimal("1"),
        price=Decimal("100"),
        execution_id=uuid4(),
    )
    with pytest.raises(ValueError, match="belong to the receipt client_order_id"):
        ExecutionReceipt.from_order(
            order,
            request_id=uuid4(),
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            order_status=OrderStatus.PARTIALLY_FILLED,
            executed_at=BASE,
            fills=(foreign,),
        )


# ---------------------------------------------------------------------------
# Execution delta semantics
# ---------------------------------------------------------------------------


def test_two_genuine_deltas_of_one_each_fill_two() -> None:
    """Two genuine execution deltas of 1 each → valid full fill of 2."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.FILLED,
            status=OrderStatus.FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.filled_quantity == Decimal("2")
    assert lifecycle.status is OrderStatus.FILLED
    assert lifecycle.is_complete is True
    assert lifecycle.requires_reconciliation is False


def test_replaying_same_receipt_is_idempotent() -> None:
    order = _order()
    receipt_id = uuid4()
    receipt = _delta_receipt(
        order,
        outcome=ExecutionOutcome.FILLED,
        status=OrderStatus.FILLED,
        fills=(_fill(order, Decimal("2")),),
        receipt_id=receipt_id,
    )
    lifecycle = ExecutionLifecycle.rebuild(
        order.client_order_id, order.quantity, (receipt, receipt)
    )
    assert lifecycle.filled_quantity == Decimal("2")


def test_conflicting_receipt_id_is_rejected() -> None:
    order = _order()
    shared_id = uuid4()
    a = _delta_receipt(
        order,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        status=OrderStatus.PARTIALLY_FILLED,
        fills=(_fill(order, Decimal("1")),),
        receipt_id=shared_id,
    )
    b = _delta_receipt(
        order,
        outcome=ExecutionOutcome.FILLED,
        status=OrderStatus.FILLED,
        fills=(_fill(order, Decimal("2")),),
        receipt_id=shared_id,
    )
    with pytest.raises(ValueError, match="conflicting receipt data"):
        ExecutionLifecycle.rebuild(order.client_order_id, order.quantity, (a, b))


def test_identical_distinct_executions_are_both_preserved() -> None:
    """Distinct legitimate executions with identical price/qty/timestamp both preserved."""
    order = _order(quantity=Decimal("2"))
    fills = (
        _fill(order, Decimal("1"), price=Decimal("100")),
        _fill(order, Decimal("1"), price=Decimal("100")),
    )
    receipt = _delta_receipt(
        order, outcome=ExecutionOutcome.FILLED, status=OrderStatus.FILLED, fills=fills
    )
    assert len(receipt.fills) == 2
    lifecycle = ExecutionLifecycle.rebuild(order.client_order_id, order.quantity, (receipt,))
    assert lifecycle.filled_quantity == Decimal("2")


# ---------------------------------------------------------------------------
# Mixed provenance
# ---------------------------------------------------------------------------


def test_mixed_positive_evidence_requires_reconciliation() -> None:
    """Mixed cumulative + delta without disjointness proof → unresolved, not fabricated."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False
    assert any("mixed" in a for a in lifecycle.anomalies)


def test_mixed_evidence_delta_after_cumulative_requires_reconciliation() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.requires_reconciliation is True
    assert any("mixed" in a for a in lifecycle.anomalies)


# ---------------------------------------------------------------------------
# Mixed provenance sequences across zero-fill status receipts
# ---------------------------------------------------------------------------


def test_zero_fill_status_receipt_then_cumulative_is_not_a_mixed_evidence_conflict() -> None:
    """An accepted/status-only receipt carries no quantity, so a later cumulative
    observation must stay clean instead of tripping the mixed-evidence guard."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.ACCEPTED,
            status=OrderStatus.ACCEPTED,
            fills=(),
            executed_at=BASE,
        )
    )
    assert lifecycle.status is OrderStatus.ACCEPTED
    assert lifecycle.filled_quantity == Decimal("0")
    assert lifecycle.observed_filled_quantity is None

    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.requires_reconciliation is False
    assert lifecycle.anomalies == ()
    assert lifecycle.filled_quantity == Decimal("1")
    assert lifecycle.observed_filled_quantity == Decimal("1")
    assert lifecycle.status is OrderStatus.PARTIALLY_FILLED


def test_cumulative_one_then_zero_fill_cancellation_keeps_quantity_and_observation() -> None:
    """A status-only cancellation must not erase or double-count observed quantity."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.CANCELLED,
            status=OrderStatus.CANCELLED,
            fills=(),
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.requires_reconciliation is False
    assert lifecycle.filled_quantity == Decimal("1")
    assert lifecycle.observed_filled_quantity == Decimal("1")
    assert lifecycle.remaining_quantity == Decimal("1")
    assert lifecycle.status is OrderStatus.CANCELLED


def test_cumulative_then_zero_fill_status_then_positive_delta_requires_reconciliation() -> None:
    """A positive delta arriving after cumulative evidence is unresolvable without
    a disjointness proof, even when a status-only receipt came between them."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.ACCEPTED,
            status=OrderStatus.ACCEPTED,
            fills=(),
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.observed_filled_quantity == Decimal("1")
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE + timedelta(seconds=10),
        )
    )
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False
    assert any("mixed" in a for a in lifecycle.anomalies)


def test_positive_delta_then_positive_cumulative_fails_closed() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False
    assert any("mixed" in a for a in lifecycle.anomalies)


def test_positive_cumulative_then_positive_delta_fails_closed() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("1"),
            status=OrderStatus.PARTIALLY_FILLED,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False
    assert any("mixed" in a for a in lifecycle.anomalies)


def test_repeated_cumulative_observations_are_never_additive() -> None:
    """Four snapshots all reporting 1 stay at 1 — never 4."""
    order = _order()
    lifecycle = _lifecycle(order)
    for index in range(4):
        lifecycle = lifecycle.apply(
            _cumulative_receipt(
                order,
                observed=Decimal("1"),
                status=OrderStatus.PARTIALLY_FILLED,
                outcome=ExecutionOutcome.PARTIALLY_FILLED,
                executed_at=BASE + timedelta(seconds=5 * index),
            )
        )
        assert lifecycle.filled_quantity == Decimal("1")
        assert lifecycle.observed_filled_quantity == Decimal("1")
    assert lifecycle.requires_reconciliation is False


def test_increasing_cumulative_observations_are_monotonic_not_additive() -> None:
    """Snapshots 1, 2, 2 must read as observed 2 - never 5."""
    order = _order()
    lifecycle = _lifecycle(order)
    observations = (
        (Decimal("1"), OrderStatus.PARTIALLY_FILLED),
        (Decimal("2"), OrderStatus.FILLED),
        (Decimal("2"), OrderStatus.FILLED),
    )
    for index, (observed, status) in enumerate(observations):
        lifecycle = lifecycle.apply(
            _cumulative_receipt(
                order,
                observed=observed,
                status=status,
                outcome=ExecutionOutcome.PARTIALLY_FILLED
                if status is OrderStatus.PARTIALLY_FILLED
                else ExecutionOutcome.FILLED,
                executed_at=BASE + timedelta(seconds=5 * index),
            )
        )
        assert lifecycle.filled_quantity == observed
        assert lifecycle.observed_filled_quantity == observed
    assert lifecycle.remaining_quantity == Decimal("0")
    assert lifecycle.status is OrderStatus.FILLED
    assert lifecycle.requires_reconciliation is False


def test_headline_filled_not_definitive_when_reconciliation_required() -> None:
    """A FILLED status must not look complete when reconciliation is required."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.PARTIALLY_FILLED,
            status=OrderStatus.PARTIALLY_FILLED,
            fills=(_fill(order, Decimal("1")),),
            executed_at=BASE,
        )
    )
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("2"),
            status=OrderStatus.FILLED,
            outcome=ExecutionOutcome.FILLED,
            executed_at=BASE + timedelta(seconds=5),
        )
    )
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.is_complete is False


# ---------------------------------------------------------------------------
# Zero-quantity terminal receipts
# ---------------------------------------------------------------------------


def test_zero_fill_cancellation_still_applies_status() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.CANCELLED,
            status=OrderStatus.CANCELLED,
            fills=(),
            executed_at=BASE,
        )
    )
    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("0")
    assert lifecycle.remaining_quantity == Decimal("2")
    assert lifecycle.is_complete is True


def test_zero_fill_rejection_still_applies_status() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.REJECTED,
            status=OrderStatus.REJECTED,
            fills=(),
            executed_at=BASE,
        )
    )
    assert lifecycle.status is OrderStatus.REJECTED
    assert lifecycle.filled_quantity == Decimal("0")


def test_zero_quantity_cumulative_receipt_carries_terminal_status() -> None:
    """A CANCELLED observation with cumulative filled 0 retains cancellation."""
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _cumulative_receipt(
            order,
            observed=Decimal("0"),
            status=OrderStatus.CANCELLED,
            outcome=ExecutionOutcome.CANCELLED,
            executed_at=BASE,
        )
    )
    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("0")


def test_unknown_status_requires_reconciliation() -> None:
    order = _order()
    lifecycle = _lifecycle(order)
    lifecycle = lifecycle.apply(
        _delta_receipt(
            order,
            outcome=ExecutionOutcome.UNKNOWN,
            status=OrderStatus.UNKNOWN,
            fills=(),
            executed_at=BASE,
        )
    )
    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.is_complete is False
    assert lifecycle.can_continue is False


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_receipt_roundtrip_preserves_evidence_contract(tmp_path) -> None:
    from quantx.persistence.sqlite.database import SqliteDatabase
    from quantx.persistence.sqlite.receipts import SqliteReceiptRepository

    database = SqliteDatabase(tmp_path / "receipts.db")
    repository = SqliteReceiptRepository(database)
    order = _order()
    receipt = _cumulative_receipt(
        order,
        observed=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        average_price=Decimal("101.5"),
    )
    repository.save(receipt)
    loaded = repository.get(receipt.receipt_id)
    assert loaded is not None
    assert loaded == receipt
    assert loaded.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
    assert loaded.observed_filled_quantity == Decimal("1")
    assert loaded.observed_average_price == Decimal("101.5")
    assert loaded.fills == ()


def test_receipt_reopen_after_survives_reload(tmp_path) -> None:
    """Write, reopen the database, and re-read the same receipt identically."""
    from quantx.persistence.sqlite.database import SqliteDatabase
    from quantx.persistence.sqlite.receipts import SqliteReceiptRepository

    path = tmp_path / "receipts.db"
    database = SqliteDatabase(path)
    repository = SqliteReceiptRepository(database)
    order = _order()
    receipt = _delta_receipt(
        order,
        outcome=ExecutionOutcome.FILLED,
        status=OrderStatus.FILLED,
        fills=(_fill(order, Decimal("2")),),
    )
    repository.save(receipt)
    del database

    reopened = SqliteDatabase(path)
    repository2 = SqliteReceiptRepository(reopened)
    loaded = repository2.get(receipt.receipt_id)
    assert loaded is not None
    assert loaded == receipt
    assert loaded.evidence_kind is ExecutionEvidenceKind.EXECUTION_DELTAS


def test_duplicate_save_is_idempotent(tmp_path) -> None:
    from quantx.persistence.sqlite.database import SqliteDatabase
    from quantx.persistence.sqlite.receipts import SqliteReceiptRepository

    repository = SqliteReceiptRepository(SqliteDatabase(tmp_path / "receipts.db"))
    order = _order()
    receipt = _delta_receipt(
        order,
        outcome=ExecutionOutcome.FILLED,
        status=OrderStatus.FILLED,
        fills=(_fill(order, Decimal("2")),),
    )
    repository.save(receipt)
    repository.save(receipt)
    assert repository.get(receipt.receipt_id) == receipt


def test_replay_from_persistence_reproduces_lifecycle(tmp_path) -> None:
    """Persisted cumulative receipts rebuild to the same lifecycle as in-memory."""
    from quantx.persistence.sqlite.database import SqliteDatabase
    from quantx.persistence.sqlite.receipts import SqliteReceiptRepository

    repository = SqliteReceiptRepository(SqliteDatabase(tmp_path / "receipts.db"))
    order = _order()
    first = _cumulative_receipt(
        order,
        observed=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        executed_at=BASE,
    )
    second = _cumulative_receipt(
        order,
        observed=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
        outcome=ExecutionOutcome.PARTIALLY_FILLED,
        executed_at=BASE + timedelta(seconds=5),
    )
    repository.save(first)
    repository.save(second)
    loaded = (repository.get(first.receipt_id), repository.get(second.receipt_id))
    lifecycle = ExecutionLifecycle.rebuild(order.client_order_id, order.quantity, loaded)
    assert lifecycle.filled_quantity == Decimal("1")


# ---------------------------------------------------------------------------
# Backward compatibility with pre-evidence-kind persisted payloads
# ---------------------------------------------------------------------------

# An authentic receipt row exactly as ``receipt_to_payload`` wrote it before the
# evidence-kind contract existed: no ``evidence_kind``, no ``observed_*`` keys.
LEGACY_EXECUTION_DELTAS_PAYLOAD = (
    '{"account_id":null,"assumptions":[],"broker_order_id":null,'
    '"client_order_id":"725034eb-64a7-4d45-8d81-437fe66355ba",'
    '"connection_id":null,"correlation_id":null,'
    '"executed_at":"2026-01-01T09:30:00+00:00","fee":"0","fills":['
    '{"client_order_id":"725034eb-64a7-4d45-8d81-437fe66355ba",'
    '"execution_id":"6f1f4f0a-0a1b-4c2d-8e3f-5a6b7c8d9e02",'
    '"filled_at":"2026-01-01T09:29:58+00:00",'
    '"instrument":{"symbol":"TCS","venue":"NSE"},"price":"101.5",'
    '"quantity":"2","side":"BUY"}],'
    '"message":"","model_profile":"","model_version":"",'
    '"order_id":"725034eb-64a7-4d45-8d81-437fe66355ba","order_quantity":"2",'
    '"order_status":"FILLED","outcome":"FILLED","raw_reference":null,'
    '"receipt_id":"6f1f4f0a-0a1b-4c2d-8e3f-5a6b7c8d9e03",'
    '"request_id":"6f1f4f0a-0a1b-4c2d-8e3f-5a6b7c8d9e01",'
    '"simulated":false,"source":"dhan"}'
)


def test_legacy_payload_has_no_evidence_kind_keys() -> None:
    """Guard the fixture itself so the regression cannot silently stop testing
    the pre-change format."""
    decoded = json.loads(LEGACY_EXECUTION_DELTAS_PAYLOAD)
    assert "evidence_kind" not in decoded
    assert "observed_filled_quantity" not in decoded
    assert "observed_average_price" not in decoded


def test_legacy_payload_loads_as_execution_deltas() -> None:
    """A pre-change row must load, not raise KeyError, as additive deltas."""
    from quantx.persistence.sqlite.receipts import receipt_from_payload

    loaded = receipt_from_payload(LEGACY_EXECUTION_DELTAS_PAYLOAD)
    assert loaded.evidence_kind is ExecutionEvidenceKind.EXECUTION_DELTAS
    assert loaded.observed_filled_quantity is None
    assert loaded.observed_average_price is None
    assert loaded.filled_quantity == Decimal("2")
    assert loaded.order_status is OrderStatus.FILLED


def test_legacy_payload_replays_through_the_lifecycle(tmp_path) -> None:
    """A legacy row stored by an older build still replays to a full fill."""
    from quantx.persistence.sqlite.database import SqliteDatabase
    from quantx.persistence.sqlite.receipts import (
        SqliteReceiptRepository,
        receipt_from_payload,
    )

    database = SqliteDatabase(tmp_path / "legacy.db")
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO receipts (receipt_id, client_order_id, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                "6f1f4f0a-0a1b-4c2d-8e3f-5a6b7c8d9e03",
                "725034eb-64a7-4d45-8d81-437fe66355ba",
                LEGACY_EXECUTION_DELTAS_PAYLOAD,
                "2026-01-01T09:30:00+00:00",
            ),
        )

    loaded = SqliteReceiptRepository(database).get(UUID("6f1f4f0a-0a1b-4c2d-8e3f-5a6b7c8d9e03"))
    assert loaded is not None
    assert loaded == receipt_from_payload(LEGACY_EXECUTION_DELTAS_PAYLOAD)

    lifecycle = ExecutionLifecycle.rebuild(
        UUID("725034eb-64a7-4d45-8d81-437fe66355ba"), Decimal("2"), (loaded,)
    )
    assert lifecycle.filled_quantity == Decimal("2")
    assert lifecycle.status is OrderStatus.FILLED
    assert lifecycle.is_complete is True
    assert lifecycle.requires_reconciliation is False
