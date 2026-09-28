from uuid import uuid4

from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.preconditions.models import PreconditionsResult, PreconditionsStatus
from quantx.execution.transactions.coordinator import ExecutionTransactionCoordinator


def _request(client_order_id):
    request = type("Request", (), {})()
    request.order = type("Order", (), {"client_order_id": client_order_id})()
    return request


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
        def complete(self, client_order_id, receipt_id) -> None:
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
