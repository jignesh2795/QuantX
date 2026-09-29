from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.persistence.sqlite.database import SqliteDatabase
from quantx.persistence.sqlite.receipts import SqliteReceiptRepository


def _receipt(
    client_order_id,
    *,
    correlation_id: str,
    quantity: Decimal,
    filled: Decimal,
    status: OrderStatus,
    executed_at: datetime,
) -> ExecutionReceipt:
    fills = ()
    if filled:
        fills = (
            Fill(
                client_order_id=client_order_id,
                instrument=InstrumentId("NSE", "TCS"),
                side=OrderSide.BUY,
                quantity=filled,
                price=Decimal("100"),
                filled_at=executed_at,
                execution_id=uuid4(),
            ),
        )
    outcome = {
        OrderStatus.PARTIALLY_FILLED: ExecutionOutcome.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionOutcome.FILLED,
        OrderStatus.UNKNOWN: ExecutionOutcome.UNKNOWN,
    }[status]
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_order_id,
        outcome=outcome,
        order_status=status,
        executed_at=executed_at,
        fills=fills,
        correlation_id=correlation_id,
        order_id=client_order_id,
        order_quantity=quantity,
    )


def test_sqlite_receipts_can_rebuild_parent_lifecycle_after_restart(tmp_path: Path) -> None:
    parent_id = uuid4()
    child_id = uuid4()
    at = datetime(2026, 1, 1, tzinfo=UTC)
    parent = _receipt(
        parent_id,
        correlation_id=str(parent_id),
        quantity=Decimal("10"),
        filled=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
        executed_at=at,
    )
    child = _receipt(
        child_id,
        correlation_id=str(parent_id),
        quantity=Decimal("6"),
        filled=Decimal("6"),
        status=OrderStatus.FILLED,
        executed_at=at + timedelta(seconds=1),
    )

    database = SqliteDatabase(tmp_path / "execution.sqlite")
    repository = SqliteReceiptRepository(database)
    repository.save(parent)
    repository.save(child)
    database.close()

    reopened = SqliteDatabase(tmp_path / "execution.sqlite")
    reopened_repository = SqliteReceiptRepository(reopened)
    receipts = reopened_repository.list_by_correlation_id(parent_id)
    lifecycle = ExecutionLifecycle.rebuild(parent_id, Decimal("10"), receipts)

    assert [receipt.receipt_id for receipt in receipts] == [parent.receipt_id, child.receipt_id]
    assert lifecycle.filled_quantity == Decimal("10")
    assert lifecycle.remaining_quantity == Decimal("0")
    assert lifecycle.status is OrderStatus.FILLED
    assert lifecycle.is_complete
    reopened.close()


def test_rebuilding_duplicate_receipt_does_not_double_count() -> None:
    parent_id = uuid4()
    receipt = _receipt(
        parent_id,
        correlation_id=str(parent_id),
        quantity=Decimal("10"),
        filled=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    lifecycle = ExecutionLifecycle.rebuild(
        parent_id,
        Decimal("10"),
        (receipt, receipt),
    )

    assert lifecycle.filled_quantity == Decimal("4")
    assert lifecycle.remaining_quantity == Decimal("6")
    assert lifecycle.status is OrderStatus.PARTIALLY_FILLED


def test_missing_child_receipt_preserves_evidenced_remainder() -> None:
    parent_id = uuid4()
    receipt = _receipt(
        parent_id,
        correlation_id=str(parent_id),
        quantity=Decimal("10"),
        filled=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    lifecycle = ExecutionLifecycle.rebuild(parent_id, Decimal("10"), (receipt,))

    assert lifecycle.filled_quantity == Decimal("4")
    assert lifecycle.remaining_quantity == Decimal("6")
    assert lifecycle.can_continue


def test_wrong_parent_correlation_is_not_accepted_by_rebuild() -> None:
    parent_id = uuid4()
    other_id = uuid4()
    receipt = _receipt(
        uuid4(),
        correlation_id=str(other_id),
        quantity=Decimal("6"),
        filled=Decimal("6"),
        status=OrderStatus.FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="does not belong"):
        ExecutionLifecycle.rebuild(parent_id, Decimal("10"), (receipt,))


def test_unknown_receipt_rebuild_is_fail_closed() -> None:
    parent_id = uuid4()
    receipt = _receipt(
        parent_id,
        correlation_id=str(parent_id),
        quantity=Decimal("10"),
        filled=Decimal("0"),
        status=OrderStatus.UNKNOWN,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    lifecycle = ExecutionLifecycle.rebuild(parent_id, Decimal("10"), (receipt,))

    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.remaining_quantity == Decimal("10")
    assert not lifecycle.can_continue
    assert lifecycle.is_complete
