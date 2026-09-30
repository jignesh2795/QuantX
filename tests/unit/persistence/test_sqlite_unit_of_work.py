"""SQLite adapter tests: idempotency, receipts, and unit-of-work behavior."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier, Thread
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteIdempotencyStore,
    SqliteReceiptRepository,
    SqliteUnitOfWork,
)


def _receipt(client_order_id=None) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_order_id or uuid4(),
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="sqlite-test",
    )


def _filled_receipt() -> ExecutionReceipt:
    order_id = uuid4()
    fill = Fill(
        client_order_id=order_id,
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        price=Decimal("100"),
        filled_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        fills=(fill,),
        message="filled",
        simulated=True,
        source="sqlite-test",
        model_profile="test",
        model_version="v1",
        assumptions=("a", "b"),
        fee=Decimal("1.5"),
        broker_order_id="broker-1",
        raw_reference="raw",
        correlation_id=str(order_id),
        order_id=order_id,
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )


def test_receipt_save_get_round_trip(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _receipt()
        repository.save(receipt)
        assert repository.get(receipt.receipt_id) == receipt


def test_get_by_client_order(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _receipt()
        repository.save(receipt)
        assert repository.get_by_client_order(receipt.client_order_id) == receipt
        assert repository.get_by_client_order(uuid4()) is None


def test_receipt_repository_is_authoritative(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _receipt()
        repository.save(receipt)
        assert repository.get(receipt.receipt_id) == receipt
        assert repository.get(uuid4()) is None


def test_conflicting_receipt_id_cannot_overwrite(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _receipt()
        repository.save(receipt)
        conflicting = replace(receipt, message="conflicting")
        with pytest.raises(ValueError, match="overwrite"):
            repository.save(conflicting)
        assert repository.get(receipt.receipt_id) == receipt


def test_reservation_acquisition(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        decision = store.reserve_or_get(uuid4(), "fingerprint-a")
        assert decision.reservation_acquired
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None


def test_same_order_duplicate_is_pending(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        store.reserve_or_get(order_id, "fingerprint-a")
        second = store.reserve_or_get(order_id, "fingerprint-a")
        assert not second.reservation_acquired
        assert second.reservation_pending
        assert second.existing_receipt_id is None


def test_fingerprint_mismatch(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        store.reserve_or_get(order_id, "fingerprint-a")
        with pytest.raises(ValueError, match="different request"):
            store.reserve_or_get(order_id, "fingerprint-b")
        decision = store.check(order_id, "fingerprint-a")
        assert decision.reservation_pending


def test_completion(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        receipt_id = uuid4()
        store.reserve_or_get(order_id, "fingerprint-a")
        store.complete(order_id, "fingerprint-a", receipt_id)
        decision = store.check(order_id, "fingerprint-a")
        assert decision.existing_receipt_id == receipt_id
        assert not decision.reservation_pending


def test_double_completion_rejected(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        store.reserve_or_get(order_id, "fingerprint-a")
        store.complete(order_id, "fingerprint-a", uuid4())
        with pytest.raises(ValueError, match="already completed"):
            store.complete(order_id, "fingerprint-a", uuid4())


def test_resolve_pending(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        receipt_id = uuid4()
        store.reserve_or_get(order_id, "fingerprint-a")
        with pytest.raises(ValueError, match="different request"):
            store.resolve_pending(order_id, "fingerprint-b", receipt_id)
        with pytest.raises(ValueError, match="non-pending"):
            store.resolve_pending(uuid4(), "fingerprint-a", receipt_id)
        store.resolve_pending(order_id, "fingerprint-a", receipt_id)
        decision = store.check(order_id, "fingerprint-a")
        assert decision.existing_receipt_id == receipt_id


def test_unit_of_work_commit(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        uow = SqliteUnitOfWork(database)
        order_id = uuid4()
        receipt = _receipt(order_id)
        with uow:
            uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
            uow.receipts.save(receipt)
            uow.idempotency.complete(order_id, "fingerprint-a", receipt.receipt_id)
        assert SqliteReceiptRepository(database).get(receipt.receipt_id) == receipt
        decision = SqliteIdempotencyStore(database).check(order_id, "fingerprint-a")
        assert decision.existing_receipt_id == receipt.receipt_id


def test_unit_of_work_rollback(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        uow = SqliteUnitOfWork(database)
        order_id = uuid4()
        receipt = _receipt(order_id)
        with pytest.raises(RuntimeError, match="boom"):
            with uow:
                uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
                uow.receipts.save(receipt)
                raise RuntimeError("boom")
        assert SqliteReceiptRepository(database).get(receipt.receipt_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fingerprint-a")
        assert not decision.reservation_pending
        assert decision.existing_receipt_id is None


def test_receipt_and_completion_share_one_transaction(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        uow = SqliteUnitOfWork(database)
        order_id = uuid4()
        receipt = _receipt(order_id)
        with uow:
            uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
            uow.receipts.save(receipt)
            uow.idempotency.complete(order_id, "fingerprint-a", receipt.receipt_id)
    with SqliteDatabase(path) as reopened:
        assert SqliteReceiptRepository(reopened).get(receipt.receipt_id) == receipt
        decision = SqliteIdempotencyStore(reopened).check(order_id, "fingerprint-a")
        assert decision.existing_receipt_id == receipt.receipt_id


def test_rollback_removes_both_receipt_and_completion(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        uow = SqliteUnitOfWork(database)
        order_id = uuid4()
        receipt = _receipt(order_id)
        with pytest.raises(RuntimeError, match="boom"):
            with uow:
                uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
                uow.receipts.save(receipt)
                uow.idempotency.complete(order_id, "fingerprint-a", receipt.receipt_id)
                raise RuntimeError("boom")
        assert SqliteReceiptRepository(database).get(receipt.receipt_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fingerprint-a")
        assert not decision.reservation_pending
        assert decision.existing_receipt_id is None


def test_reopen_persistence(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        receipt = _receipt()
        SqliteReceiptRepository(database).save(receipt)
    with SqliteDatabase(path) as reopened:
        assert SqliteReceiptRepository(reopened).get(receipt.receipt_id) == receipt


def test_pending_survives_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    order_id = uuid4()
    with SqliteDatabase(path) as database:
        SqliteIdempotencyStore(database).reserve_or_get(order_id, "fingerprint-a")
    with SqliteDatabase(path) as reopened:
        decision = SqliteIdempotencyStore(reopened).check(order_id, "fingerprint-a")
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None


def test_threaded_same_order_single_acquirer(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        order_id = uuid4()
        barrier = Barrier(2)
        outcomes = []

        def attempt():
            barrier.wait(timeout=10)
            outcomes.append(store.reserve_or_get(order_id, "fingerprint-a"))

        threads = [Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)
        assert len(outcomes) == 2
        assert sum(1 for decision in outcomes if decision.reservation_acquired) == 1


def test_busy_database_fails_closed(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path, timeout=0.2) as database:
        raw = sqlite3.connect(str(path), timeout=5.0)
        try:
            raw.execute("BEGIN IMMEDIATE")
            raw.execute(
                "INSERT INTO idempotency_reservations "
                "(client_order_id, fingerprint, receipt_id, created_at, completed_at) "
                "VALUES (?, ?, NULL, ?, NULL)",
                (str(uuid4()), "fingerprint-a", "2026-01-01T00:00:00+00:00"),
            )
            store = SqliteIdempotencyStore(database)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                store.reserve_or_get(uuid4(), "fingerprint-a")
        finally:
            raw.rollback()
            raw.close()
        decision = store.reserve_or_get(uuid4(), "fingerprint-b")
        assert decision.reservation_acquired


def test_receipt_serialization_round_trip(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _filled_receipt()
        repository.save(receipt)
        assert repository.get(receipt.receipt_id) == receipt
        assert repository.get_by_client_order(receipt.client_order_id) == receipt


def test_receipt_immutability(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteReceiptRepository(database)
        receipt = _receipt()
        repository.save(receipt)
        repository.save(receipt)
        assert repository.get(receipt.receipt_id) == receipt


def test_nested_unit_of_work_rejected(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        uow = SqliteUnitOfWork(database)
        with uow:
            with pytest.raises(RuntimeError, match="nested"):
                with uow:
                    pass


def test_malformed_pending_context_is_reported_without_blocking_listing(tmp_path) -> None:
    order_id = uuid4()
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO idempotency_reservations "
                "(client_order_id, fingerprint, receipt_id, created_at, completed_at, "
                "pending_context_json) VALUES (?, ?, NULL, ?, NULL, ?)",
                (
                    str(order_id),
                    "fingerprint-a",
                    datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                    "{malformed-json",
                ),
            )
        records = store.list_pending_recovery_records()
        assert len(records) == 1
        assert records[0].client_order_id == str(order_id)
        assert records[0].context is None
        assert records[0].error is not None
        assert "invalid pending execution context" in records[0].error
        assert store.list_pending_contexts() == ()
