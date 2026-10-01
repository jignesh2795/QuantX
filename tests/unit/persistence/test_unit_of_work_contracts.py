"""Contract tests for the database-neutral persistence boundary.

Fakes live in this module only; no fake persistent adapter is shipped as
production code. Idempotency semantics are inherited from the frozen
in-memory store so the contract preserves them instead of redefining them.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.persistence import PersistentIdempotencyStore, ReceiptRepository, UnitOfWork


class _TransactionalFakeStore(InMemoryIdempotencyStore):
    """Frozen semantics plus snapshot/restore for rollback tests."""

    def snapshot(self):
        return (dict(self._fingerprints), dict(self._receipts))

    def restore(self, snapshot) -> None:
        fingerprints, receipts = snapshot
        self._fingerprints.clear()
        self._fingerprints.update(fingerprints)
        self._receipts.clear()
        self._receipts.update(receipts)


class _FakeReceiptRepository(ReceiptRepository):
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def save(self, receipt: ExecutionReceipt) -> None:
        self._uow._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id: UUID) -> ExecutionReceipt | None:
        return self._uow._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id: UUID) -> ExecutionReceipt | None:
        for receipt in self._uow._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None


class _FakeUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self._store = _TransactionalFakeStore()
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._store_snapshot = None
        self._receipts_snapshot = None
        self.committed = False
        self.rolled_back = False

    @property
    def idempotency(self) -> PersistentIdempotencyStore:
        return self._store

    @property
    def receipts(self) -> ReceiptRepository:
        return _FakeReceiptRepository(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        if self._store_snapshot is not None:
            self._store.restore(self._store_snapshot)
        if self._receipts_snapshot is not None:
            self._receipts.clear()
            self._receipts.update(self._receipts_snapshot)
        self.rolled_back = True

    def __enter__(self) -> UnitOfWork:
        self._store_snapshot = self._store.snapshot()
        self._receipts_snapshot = dict(self._receipts)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


def _receipt(client_order_id=None) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_order_id or uuid4(),
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="contract-test",
    )


def test_reservation_acquired_atomically() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    first = uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    assert first.reservation_acquired
    assert first.reservation_pending
    second = uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    assert not second.reservation_acquired
    assert second.reservation_pending
    assert second.existing_receipt_id is None


def test_fingerprint_mismatch_rejected() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    with pytest.raises(ValueError, match="different request"):
        uow.idempotency.reserve_or_get(order_id, "fingerprint-b")


def test_pending_is_not_retryable() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    decision = uow.idempotency.check(order_id, "fingerprint-a")
    assert decision.reservation_pending
    assert decision.existing_receipt_id is None


def test_completion_requires_fingerprint_and_state() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    receipt_id = uuid4()
    with pytest.raises(ValueError, match="unreserved"):
        uow.idempotency.complete(order_id, "fingerprint-a", receipt_id)
    uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    with pytest.raises(ValueError, match="different request"):
        uow.idempotency.complete(order_id, "fingerprint-b", receipt_id)
    uow.idempotency.complete(order_id, "fingerprint-a", receipt_id)
    with pytest.raises(ValueError, match="already completed"):
        uow.idempotency.complete(order_id, "fingerprint-a", uuid4())
    decision = uow.idempotency.check(order_id, "fingerprint-a")
    assert decision.existing_receipt_id == receipt_id
    assert not decision.reservation_pending


def test_resolution_requires_fingerprint_and_state() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    receipt_id = uuid4()
    uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
    with pytest.raises(ValueError, match="different request"):
        uow.idempotency.resolve_pending(order_id, "fingerprint-b", receipt_id)
    with pytest.raises(ValueError, match="non-pending"):
        uow.idempotency.resolve_pending(uuid4(), "fingerprint-a", receipt_id)
    uow.idempotency.resolve_pending(order_id, "fingerprint-a", receipt_id)
    decision = uow.idempotency.check(order_id, "fingerprint-a")
    assert decision.existing_receipt_id == receipt_id


def test_unit_of_work_groups_receipt_and_completion() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    receipt = _receipt(order_id)
    with uow:
        uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
        uow.receipts.save(receipt)
        uow.idempotency.complete(order_id, "fingerprint-a", receipt.receipt_id)
    assert uow.committed
    assert uow.receipts.get(receipt.receipt_id) == receipt
    decision = uow.idempotency.check(order_id, "fingerprint-a")
    assert decision.existing_receipt_id == receipt.receipt_id


def test_unit_of_work_rolls_back_on_error() -> None:
    uow = _FakeUnitOfWork()
    order_id = uuid4()
    receipt = _receipt(order_id)
    with pytest.raises(RuntimeError, match="boom"):
        with uow:
            uow.idempotency.reserve_or_get(order_id, "fingerprint-a")
            uow.receipts.save(receipt)
            raise RuntimeError("boom")
    assert uow.rolled_back
    assert not uow.committed
    assert uow.receipts.get(receipt.receipt_id) is None
    decision = uow.idempotency.check(order_id, "fingerprint-a")
    assert not decision.reservation_pending
    assert decision.existing_receipt_id is None


def test_receipt_repository_is_authoritative() -> None:
    uow = _FakeUnitOfWork()
    receipt = _receipt()
    uow.receipts.save(receipt)
    assert uow.receipts.get(receipt.receipt_id) == receipt
    assert uow.receipts.get_by_client_order(receipt.client_order_id) == receipt
    assert uow.receipts.get(uuid4()) is None


def test_cache_cannot_override_persisted_receipt() -> None:
    uow = _FakeUnitOfWork()
    receipt = _receipt()
    uow.receipts.save(receipt)
    cache = {receipt.client_order_id: _receipt(receipt.client_order_id)}
    assert not hasattr(uow, "cache")
    authoritative = uow.receipts.get_by_client_order(receipt.client_order_id)
    assert authoritative == receipt
    assert authoritative != cache[receipt.client_order_id]
