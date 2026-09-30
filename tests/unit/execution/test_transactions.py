from datetime import UTC, datetime
from uuid import uuid4

from quantx.domain.deployment import ExecutionMode
from quantx.domain.enums import OrderStatus
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.preconditions.models import PreconditionsResult, PreconditionsStatus
from quantx.execution.transactions.coordinator import ExecutionTransactionCoordinator
from quantx.persistence import ReceiptRepository


def _request(client_order_id):
    request = type("Request", (), {})()
    request.order = type("Order", (), {"client_order_id": client_order_id})()
    return request


class _FakeReceiptRepository(ReceiptRepository):
    def __init__(self) -> None:
        self._receipts = {}

    def save(self, receipt) -> None:
        self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id):
        return self._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id):
        for receipt in self._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None


def _receipt(client_order_id):
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=client_order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="repository-test",
    )


def test_live_execution_is_blocked_before_submission() -> None:
    client_order_id = uuid4()
    request = _request(client_order_id)
    request.execution_context = type(
        "ExecutionContext", (), {"execution_mode": ExecutionMode.LIVE}
    )()
    called = False

    def submit(_):
        nonlocal called
        called = True
        raise AssertionError("legacy coordinator must not submit LIVE")

    coordinator = ExecutionTransactionCoordinator(
        idempotency=InMemoryIdempotencyStore(),
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
    )

    result = coordinator.execute(request)

    assert result.status is PreconditionsStatus.BLOCKED
    assert "ExecutionOrchestrator" in result.reasons[0]
    assert called is False


def test_submission_exception_enters_unknown_and_preserves_reservation(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0

    def submit(_):
        nonlocal calls
        calls += 1
        raise RuntimeError("transport timeout")

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
    )

    result = coordinator.execute(_request(client_order_id))

    assert result.status is PreconditionsStatus.UNKNOWN
    assert result.receipt is None
    assert "unknown" in result.reasons[0]
    assert "reconciliation" in result.reasons[0]
    assert calls == 1

    decision = store.check(client_order_id, "fingerprint-a")
    assert decision.existing_receipt_id is None
    assert decision.reservation_pending


def test_pending_submission_cannot_be_retried(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0

    def submit(_):
        nonlocal calls
        calls += 1
        raise RuntimeError("transport timeout")

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
    )

    first = coordinator.execute(_request(client_order_id))
    second = coordinator.execute(_request(client_order_id))

    assert first.status is PreconditionsStatus.UNKNOWN
    assert second.status is PreconditionsStatus.UNKNOWN
    assert "reconciliation" in second.reasons[0]
    assert calls == 1


def test_idempotency_completion_failure_enters_unknown_and_blocks_retry(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0
    receipt_id = uuid4()

    def submit(_):
        nonlocal calls
        calls += 1
        receipt = type("Receipt", (), {"receipt_id": receipt_id})()
        return receipt

    class FailingCompletionStore(InMemoryIdempotencyStore):
        def complete(self, client_order_id, request_fingerprint, receipt_id) -> None:
            raise RuntimeError("persistence unavailable")

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = FailingCompletionStore()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
    )

    first = coordinator.execute(_request(client_order_id))

    assert first.status is PreconditionsStatus.UNKNOWN
    assert first.receipt is not None
    assert first.receipt.receipt_id == receipt_id
    assert "idempotency completion" in first.reasons[0]
    assert "reconciliation" in first.reasons[0]
    assert calls == 1

    second = coordinator.execute(_request(client_order_id))

    assert second.status is PreconditionsStatus.UNKNOWN
    assert second.receipt is None
    assert "reconciliation" in second.reasons[0]
    assert calls == 1


def test_duplicate_with_repository_returns_persisted_receipt(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0

    def submit(request):
        nonlocal calls
        calls += 1
        return _receipt(request.order.client_order_id)

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    repository = _FakeReceiptRepository()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
        receipt_repository=repository,
    )

    first = coordinator.execute(_request(client_order_id))
    assert first.status is PreconditionsStatus.READY
    assert first.receipt is not None
    repository.save(first.receipt)

    second = coordinator.execute(_request(client_order_id))
    assert second.status is PreconditionsStatus.READY
    assert second.receipt == first.receipt
    assert "idempotent duplicate" in second.reasons[0]
    assert calls == 1


def test_duplicate_without_repository_preserves_receipt_none(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0

    def submit(request):
        nonlocal calls
        calls += 1
        return _receipt(request.order.client_order_id)

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
    )

    first = coordinator.execute(_request(client_order_id))
    assert first.status is PreconditionsStatus.READY
    assert first.receipt is not None

    second = coordinator.execute(_request(client_order_id))
    assert second.status is PreconditionsStatus.READY
    assert second.receipt is None
    assert "idempotent duplicate" in second.reasons[0]
    assert calls == 1


def test_duplicate_with_missing_receipt_fails_closed(monkeypatch) -> None:
    client_order_id = uuid4()
    calls = 0

    def submit(request):
        nonlocal calls
        calls += 1
        return _receipt(request.order.client_order_id)

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    repository = _FakeReceiptRepository()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=submit,
        receipt_repository=repository,
    )

    first = coordinator.execute(_request(client_order_id))
    assert first.status is PreconditionsStatus.READY

    second = coordinator.execute(_request(client_order_id))
    assert second.status is PreconditionsStatus.UNKNOWN
    assert second.receipt is None
    assert "reconciliation" in second.reasons[0]
    assert calls == 1

    third = coordinator.execute(_request(client_order_id))
    assert third.status is PreconditionsStatus.UNKNOWN
    assert third.receipt is None
    assert calls == 1
