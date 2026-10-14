"""Real-path regression coverage for the receipt evidence-kind contract (QX-03).

These tests exercise the actual ExecutionReceipt model, the ExecutionLifecycle
reducer, Dhan adapter reconcile receipts, and SQLite persistence together —
not the reducer in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

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
