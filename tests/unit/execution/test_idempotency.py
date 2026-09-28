from uuid import uuid4

import pytest

from quantx.execution.idempotency import InMemoryIdempotencyStore


def test_same_client_order_id_is_idempotent() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve(order_id, "fingerprint-a")
    receipt_id = uuid4()
    store.complete(order_id, receipt_id)

    decision = store.check(order_id, "fingerprint-a")

    assert decision.existing_receipt_id == receipt_id
    assert not decision.reservation_pending


def test_pending_reservation_is_distinguished_from_completed_submission() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve(order_id, "fingerprint-a")

    decision = store.check(order_id, "fingerprint-a")

    assert decision.existing_receipt_id is None
    assert decision.reservation_pending


def test_reusing_client_order_id_for_different_request_is_blocked() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve(order_id, "fingerprint-a")

    with pytest.raises(ValueError, match="different request"):
        store.check(order_id, "fingerprint-b")
