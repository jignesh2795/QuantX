from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from quantx.execution.idempotency import InMemoryIdempotencyStore, NotSubmittedSource


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


def test_concurrent_reservation_allows_exactly_one_acquisition() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()

    def reserve() -> bool:
        return store.reserve_or_get(order_id, "fingerprint-a").reservation_acquired

    with ThreadPoolExecutor(max_workers=2) as executor:
        acquired = list(executor.map(lambda _: reserve(), range(2)))

    assert sorted(acquired) == [False, True]
    decision = store.check(order_id, "fingerprint-a")
    assert decision.reservation_pending


def _record_not_submitted(store: InMemoryIdempotencyStore, order_id, fingerprint: str) -> None:
    store.record_not_submitted(
        order_id,
        fingerprint,
        source=NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION,
        reason="preflight rejected the request before submission",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_not_submitted_closure_is_typed_and_never_an_operator_record() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")

    resolution = store.record_not_submitted(
        order_id,
        "fingerprint-a",
        source=NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION,
        reason="preflight rejected the request before submission",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert resolution.source is NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION
    assert store.get_not_submitted(order_id, "fingerprint-a") == resolution
    assert store.get_operator_resolution(order_id, "fingerprint-a") is None
    decision = store.check(order_id, "fingerprint-a")
    assert decision.not_submitted_resolution == resolution
    assert decision.reservation_pending is False
    assert decision.operator_resolved is False
    assert decision.existing_receipt_id is None


def test_not_submitted_closure_requires_a_pending_reservation() -> None:
    store = InMemoryIdempotencyStore()

    with pytest.raises(ValueError, match="unreserved"):
        _record_not_submitted(store, uuid4(), "fingerprint-a")

    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")
    store.complete(order_id, "fingerprint-a", uuid4())

    with pytest.raises(ValueError, match="completed reservation"):
        _record_not_submitted(store, order_id, "fingerprint-a")


def test_not_submitted_reservation_cannot_become_a_submission() -> None:
    store = InMemoryIdempotencyStore()
    order_id = uuid4()
    store.reserve_or_get(order_id, "fingerprint-a")
    _record_not_submitted(store, order_id, "fingerprint-a")

    with pytest.raises(ValueError, match="not submitted"):
        store.complete(order_id, "fingerprint-a", uuid4())
    with pytest.raises(ValueError, match="not submitted"):
        store.resolve_pending(order_id, "fingerprint-a", uuid4())
    with pytest.raises(ValueError, match="not submitted"):
        store.resolve_operator(
            order_id,
            "fingerprint-a",
            operator_id="ops-1",
            reason="operator closure",
            resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="already closed as not submitted"):
        _record_not_submitted(store, order_id, "fingerprint-a")
    with pytest.raises(ValueError, match="different request"):
        store.get_not_submitted(order_id, "fingerprint-b")
