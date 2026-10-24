"""Regression tests for LIVE idempotency decision validation (PR 1 completion).

Every decision under test is either produced by the real reference store or
deliberately built to model a store that returned something no store can
produce. No broker, gate or network behavior is involved.

Covered invariants:
- only the six legal ``(pending, acquired, receipt, operator, not-submitted)``
  states the in-memory and SQLite stores can produce pass the state matrix;
- flags are exact bools, so ``True == 1`` cannot smuggle an invalid state past
  the matrix;
- identity fields are exact types and are compared with the request being
  dispatched, so a foreign client order id or fingerprint is rejected;
- a pending execution context must agree with the decision it belongs to;
- an operator or not-submitted closure record must belong to the decision it
  is attached to, not to another order or another fingerprint.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import product
from uuid import UUID, uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.execution.idempotency import (
    IdempotencyDecision,
    InMemoryIdempotencyStore,
    NotSubmittedResolution,
    NotSubmittedSource,
    OperatorResolution,
    PendingExecutionContext,
    request_fingerprint,
    validate_decision_for_request,
    validate_decision_state,
)
from tests.unit._execution_request_proofs import approved_request

# The six states a reservation store can actually produce. Any other
# combination of the five flags is a state no store can reach.
_LEGAL_STATES = frozenset(
    {
        (False, False, False, False, False),  # no reservation row yet
        (True, False, False, False, False),  # held reservation
        (True, True, False, False, False),  # acquired by reserve_or_get
        (False, False, True, False, False),  # completed with a receipt
        (False, False, False, True, False),  # operator-resolved
        (False, False, False, False, True),  # closed as not submitted
    }
)


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _live_request() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
        product=ProductCode("CNC"),
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=ProductCode("CNC"),
    )


def _identity(request: ApprovedExecutionRequest) -> tuple[UUID, str]:
    return request.order.client_order_id, request_fingerprint(request)


def _binding_violation(
    decision: IdempotencyDecision, request: ApprovedExecutionRequest
) -> str | None:
    """Validate a decision against the request it is about to be used for."""
    client_order_id, fingerprint = _identity(request)
    return validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    )


def _pending_context(
    request: ApprovedExecutionRequest,
) -> PendingExecutionContext:
    client_order_id, fingerprint = _identity(request)
    return PendingExecutionContext.from_request(request, fingerprint)


def _acquired_decision(request: ApprovedExecutionRequest) -> IdempotencyDecision:
    """The decision ``reserve_or_get`` returns when it acquires the reservation."""
    client_order_id, fingerprint = _identity(request)
    store = InMemoryIdempotencyStore()
    return store.reserve_or_get(client_order_id, fingerprint, _pending_context(request))


def _store_in_state(
    request: ApprovedExecutionRequest,
    *,
    complete: bool = False,
    operator_resolve: bool = False,
    not_submitted: bool = False,
) -> IdempotencyDecision:
    """Drive the real store into one state and read it back with ``check``."""
    client_order_id, fingerprint = _identity(request)
    store = InMemoryIdempotencyStore()
    store.reserve_or_get(client_order_id, fingerprint, _pending_context(request))
    if complete:
        store.complete(client_order_id, fingerprint, uuid4())
    if operator_resolve:
        store.resolve_operator(
            client_order_id,
            fingerprint,
            operator_id="operator-1",
            reason="reviewed",
            resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    if not_submitted:
        store.record_not_submitted(
            client_order_id,
            fingerprint,
            source=NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION,
            reason="adapter rejected locally",
            recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    return store.check(client_order_id, fingerprint)


def _operator_resolution(client_order_id: UUID, fingerprint: str) -> OperatorResolution:
    return OperatorResolution(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        operator_id="operator-1",
        reason="reviewed",
        resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _not_submitted_resolution(client_order_id: UUID, fingerprint: str) -> NotSubmittedResolution:
    return NotSubmittedResolution(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        source=NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION,
        reason="adapter rejected locally",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _forced_state(
    *,
    pending: bool,
    acquired: bool,
    has_receipt: bool,
    resolved: bool,
    not_submitted: bool,
    client_order_id: UUID | None = None,
    fingerprint: str = "fp-primary",
) -> IdempotencyDecision:
    """Build a decision directly in an arbitrary flag combination.

    ``IdempotencyDecision.__post_init__`` forbids some combinations outright and
    the reference stores never produce them, so the flags are forced onto a
    valid decision. This models a store that returned something it cannot
    produce, which is exactly what the matrix must reject.
    """
    order_id = client_order_id or uuid4()
    decision = IdempotencyDecision(
        client_order_id=order_id,
        request_fingerprint=fingerprint,
    )
    object.__setattr__(decision, "reservation_pending", pending)
    object.__setattr__(decision, "reservation_acquired", acquired)
    if has_receipt:
        object.__setattr__(decision, "existing_receipt_id", uuid4())
    if resolved:
        object.__setattr__(decision, "operator_resolved", True)
        object.__setattr__(
            decision, "operator_resolution", _operator_resolution(order_id, fingerprint)
        )
    if not_submitted:
        object.__setattr__(
            decision,
            "not_submitted_resolution",
            _not_submitted_resolution(order_id, fingerprint),
        )
    return decision


@pytest.mark.parametrize(
    ("pending", "acquired", "has_receipt", "resolved", "not_submitted"),
    list(product([False, True], repeat=5)),
)
def test_state_matrix_accepts_exactly_the_states_the_stores_produce(
    pending: bool,
    acquired: bool,
    has_receipt: bool,
    resolved: bool,
    not_submitted: bool,
) -> None:
    decision = _forced_state(
        pending=pending,
        acquired=acquired,
        has_receipt=has_receipt,
        resolved=resolved,
        not_submitted=not_submitted,
    )

    violation = validate_decision_state(decision)

    legal = (pending, acquired, has_receipt, resolved, not_submitted) in _LEGAL_STATES
    assert (violation is None) is legal
    if not legal:
        assert violation == "idempotency decision is not a state the reservation store can produce"


def test_legal_state_set_has_exactly_six_states() -> None:
    assert len(_LEGAL_STATES) == 6


def test_acquired_without_pending_is_rejected() -> None:
    """PR #274 accepted this: acquired, not pending, no receipt, then submitted."""
    decision = _forced_state(
        pending=False,
        acquired=True,
        has_receipt=False,
        resolved=False,
        not_submitted=False,
    )
    assert validate_decision_state(decision) == (
        "idempotency decision is not a state the reservation store can produce"
    )


def test_receipt_with_pending_is_rejected() -> None:
    """A completed reservation cannot still be pending."""
    decision = _forced_state(
        pending=True,
        acquired=False,
        has_receipt=True,
        resolved=False,
        not_submitted=False,
    )
    assert validate_decision_state(decision) is not None


def test_receipt_with_acquired_is_rejected() -> None:
    """An acquisition cannot also carry a receipt for the same reservation."""
    decision = _forced_state(
        pending=True,
        acquired=True,
        has_receipt=True,
        resolved=False,
        not_submitted=False,
    )
    assert validate_decision_state(decision) is not None


def test_pending_with_operator_resolution_is_rejected() -> None:
    decision = _forced_state(
        pending=True,
        acquired=False,
        has_receipt=False,
        resolved=True,
        not_submitted=False,
    )
    assert validate_decision_state(decision) is not None


def test_pending_with_not_submitted_is_rejected() -> None:
    decision = _forced_state(
        pending=True,
        acquired=False,
        has_receipt=False,
        resolved=False,
        not_submitted=True,
    )
    assert validate_decision_state(decision) is not None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("reservation_pending", 1),
        ("reservation_acquired", "true"),
        ("operator_resolved", 0),
        ("operator_resolved", 1),
    ],
)
def test_non_bool_flags_are_rejected_before_the_matrix(field_name: str, value: object) -> None:
    """``True == 1`` must not be able to encode a legal-looking state."""
    decision = _forced_state(
        pending=True,
        acquired=True,
        has_receipt=False,
        resolved=False,
        not_submitted=False,
    )
    object.__setattr__(decision, field_name, value)

    assert validate_decision_state(decision) == (
        f"idempotency decision {field_name} is not an exact bool"
    )


def test_reserve_or_get_decision_passes_both_validators() -> None:
    request = _live_request()
    decision = _acquired_decision(request)

    assert _binding_violation(decision, request) is None
    assert validate_decision_state(decision) is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"complete": True}, None),
        ({"operator_resolve": True}, None),
        ({"not_submitted": True}, None),
    ],
)
def test_check_decisions_from_real_store_states_pass_both_validators(
    kwargs: dict[str, bool], expected: None
) -> None:
    request = _live_request()
    decision = _store_in_state(request, **kwargs)

    assert _binding_violation(decision, request) is expected
    assert validate_decision_state(decision) is expected


def test_unreserved_check_decision_passes_both_validators() -> None:
    request = _live_request()
    held = _store_in_state(request)

    assert _binding_violation(held, request) is None
    assert validate_decision_state(held) is None


def test_foreign_client_order_id_is_rejected() -> None:
    request = _live_request()
    _, fingerprint = _identity(request)
    decision = _acquired_decision(request)

    violation = validate_decision_for_request(
        decision, client_order_id=uuid4(), request_fingerprint=fingerprint
    )

    assert violation == "idempotency decision client_order_id does not match the request"


def test_foreign_fingerprint_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = _acquired_decision(request)

    violation = validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=f"{fingerprint}-foreign"
    )

    assert violation == "idempotency decision fingerprint does not match the request"


def test_foreign_identity_passes_the_state_matrix_but_not_the_binding() -> None:
    """The two validators are independent: the structurally legal state is not enough."""
    request = _live_request()
    _, fingerprint = _identity(request)
    decision = _acquired_decision(request)
    foreign = replace(decision, client_order_id=uuid4(), request_fingerprint="fp-foreign")

    assert validate_decision_state(foreign) is None
    assert (
        validate_decision_for_request(
            foreign, client_order_id=decision.client_order_id, request_fingerprint=fingerprint
        )
        is not None
    )


def test_non_uuid_decision_identity_is_rejected() -> None:
    request = _live_request()
    client_order_id, _ = _identity(request)
    decision = replace(
        _acquired_decision(request),
        client_order_id=str(client_order_id),
    )

    assert _binding_violation(decision, request) == (
        "idempotency decision client_order_id is not an exact UUID"
    )


@pytest.mark.parametrize("value", ["", 123, None])
def test_non_string_fingerprint_is_rejected(value: object) -> None:
    request = _live_request()
    decision = replace(_acquired_decision(request), request_fingerprint=value)

    assert _binding_violation(decision, request) == (
        "idempotency decision fingerprint is not a non-empty string"
    )


def test_non_uuid_receipt_id_is_rejected() -> None:
    request = _live_request()
    decision = _store_in_state(request, complete=True)
    forced = replace(decision, existing_receipt_id=str(decision.existing_receipt_id))

    assert _binding_violation(forced, request) == ("existing receipt id is not an exact UUID")


def test_pending_context_fingerprint_mismatch_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = _acquired_decision(request)
    context = replace(decision.pending_context, request_fingerprint="fp-other")

    violation = validate_decision_for_request(
        replace(decision, pending_context=context),
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
    )

    assert violation == "pending execution context fingerprint does not match the decision"


def test_pending_context_client_order_mismatch_is_rejected() -> None:
    request = _live_request()
    _, fingerprint = _identity(request)
    decision = _acquired_decision(request)
    foreign_order_id = uuid4()

    violation = validate_decision_for_request(
        replace(decision, client_order_id=foreign_order_id),
        client_order_id=foreign_order_id,
        request_fingerprint=fingerprint,
    )

    assert violation == "pending execution context client_order_id does not match the decision"


def test_pending_context_non_live_mode_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = _acquired_decision(request)
    context = decision.pending_context
    paper_context = replace(context.execution_context, execution_mode=ExecutionMode.PAPER)
    object.__setattr__(context, "execution_context", paper_context)

    violation = validate_decision_for_request(
        replace(decision, pending_context=context),
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
    )

    assert violation == "pending execution context mode must be LIVE"


def test_pending_context_non_enum_mode_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = _acquired_decision(request)
    context = decision.pending_context
    object.__setattr__(context.execution_context, "execution_mode", "live")

    violation = validate_decision_for_request(
        replace(decision, pending_context=context),
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
    )

    assert violation == "pending execution context mode is not an exact ExecutionMode"


def test_operator_resolution_without_the_flag_is_rejected() -> None:
    """A closure record the flag denies is a state no store produces.

    This combination is legal in the state matrix - the flag is ``False`` - so
    only the binding validator can reject it, and an unrejected decision would
    let an operator-closed reservation be reserved again.
    """
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = IdempotencyDecision(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
    )
    object.__setattr__(
        decision, "operator_resolution", _operator_resolution(client_order_id, fingerprint)
    )

    assert validate_decision_state(decision) is None
    assert validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    ) == ("operator resolution is present but the decision is not operator-resolved")


def test_operator_resolution_for_another_order_is_rejected() -> None:
    """A closure record carries its own identity, so a foreign one proves nothing."""
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = IdempotencyDecision(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        operator_resolved=True,
        operator_resolution=_operator_resolution(uuid4(), fingerprint),
    )

    assert validate_decision_state(decision) is None
    assert validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    ) == ("operator resolution does not belong to this idempotency decision")


def test_operator_resolution_with_a_foreign_fingerprint_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = IdempotencyDecision(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        operator_resolved=True,
        operator_resolution=_operator_resolution(client_order_id, "fp-other"),
    )

    assert validate_decision_state(decision) is None
    assert validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    ) == ("operator resolution does not belong to this idempotency decision")


def test_not_submitted_resolution_for_another_order_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = IdempotencyDecision(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        not_submitted_resolution=_not_submitted_resolution(client_order_id, fingerprint),
    )
    object.__setattr__(
        decision,
        "not_submitted_resolution",
        _not_submitted_resolution(uuid4(), fingerprint),
    )

    assert validate_decision_state(decision) is None
    assert validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    ) == ("not-submitted resolution does not belong to this idempotency decision")


def test_not_submitted_resolution_with_a_foreign_fingerprint_is_rejected() -> None:
    request = _live_request()
    client_order_id, fingerprint = _identity(request)
    decision = IdempotencyDecision(
        client_order_id=client_order_id,
        request_fingerprint=fingerprint,
        not_submitted_resolution=_not_submitted_resolution(client_order_id, fingerprint),
    )
    object.__setattr__(
        decision,
        "not_submitted_resolution",
        _not_submitted_resolution(client_order_id, "fp-other"),
    )

    assert validate_decision_state(decision) is None
    assert validate_decision_for_request(
        decision, client_order_id=client_order_id, request_fingerprint=fingerprint
    ) == ("not-submitted resolution does not belong to this idempotency decision")
