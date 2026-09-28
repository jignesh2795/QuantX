from uuid import uuid4

import pytest

from quantx.execution.idempotency import InMemoryIdempotencyStore


def test_same_client_order_id_is_idempotent() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    decision = store.reserve_or_get(order_id, "fingerprint-a")
    assert decision.reservation_pending
    receipt_id = uuid4()
    store.complete(order_id, "fingerprint-a", receipt_id)

    decision = store.check(order_id, "fingerprint-a")

    assert decision.existing_receipt_id == receipt_id
    assert not decision.reservation_pending


def test_pending_reservation_is_distinguished_from_completed_submission() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")

    decision = store.check(order_id, "fingerprint-a")

    assert decision.existing_receipt_id is None
    assert decision.reservation_pending


def test_reusing_client_order_id_for_different_request_is_blocked() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")

    with pytest.raises(ValueError, match="different request"):
        store.check(order_id, "fingerprint-b")


def test_atomic_reservation_returns_existing_pending_state_without_resubmitting() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()

    first = store.reserve_or_get(order_id, "fingerprint-a")
    second = store.reserve_or_get(order_id, "fingerprint-a")

    assert first.reservation_pending
    assert second.reservation_pending
    assert second.existing_receipt_id is None


def test_complete_rejects_fingerprint_mismatch() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")

    with pytest.raises(ValueError, match="different request"):
        store.complete(order_id, "fingerprint-b", uuid4())


def test_complete_rejects_already_completed_reservation() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")
    store.complete(order_id, "fingerprint-a", uuid4())

    with pytest.raises(ValueError, match="already completed"):
        store.complete(order_id, "fingerprint-a", uuid4())
