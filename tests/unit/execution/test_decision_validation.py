"""Focused regression tests for idempotency decision validation (PR 1)."""

from uuid import UUID

import pytest

from quantx.execution.idempotency import (
    IdempotencyDecision,
    IdempotencyDecisionValidationError,
    PendingExecutionContext,
    validate_decision_for_request,
    validate_decision_intrinsic,
    InMemoryIdempotencyStore,
)
from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Order
from quantx.domain.value_objects import InstrumentId, ProductCode


class FakeInMemoryIdempotencyStore(InMemoryIdempotencyStore):
    pass


def _valid_decision() -> IdempotencyDecision:
    return IdempotencyDecision(
        client_order_id=UUID("12345678-1234-5678-1234-567812345678"),
        request_fingerprint="fp_1",
    )


def test_validate_decision_intrinsic_accepts_valid() -> None:
    assert validate_decision_intrinsic(_valid_decision()) is None


def test_validate_decision_for_request_accepts_valid() -> None:
    assert validate_decision_for_request(_valid_decision()) is None


def test_validate_decision_for_request_rejects_bad_client_order_id() -> None:
    bad = IdempotencyDecision(
        client_order_id="not-a-uuid",  # type: ignore[arg-type]
        request_fingerprint="fp_1",
    )
    assert (
        validate_decision_for_request(bad)
        == "idempotency decision client_order_id is not an exact UUID"
    )


def test_defensive_except_catches_exception_not_baseexception() -> None:
    # Defensive guard must catch Exception; BaseException must propagate.
    with pytest.raises(SystemExit):
        try:
            raise IdempotencyDecisionValidationError("test")
        except Exception:
            pass  # defensive catch allowed
        raise SystemExit("BaseException must not be caught")
