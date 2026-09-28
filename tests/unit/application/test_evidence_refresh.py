"""Deterministic offline tests for reconciliation evidence refresh."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.application.evidence_refresh import (
    DefinitiveEvidencePolicy,
    ReconciliationEvidenceRefresher,
    ReconciliationIdempotencyResolver,
    RefreshPolicy,
)
from quantx.application.reconciliation import OrderWorkflowStatus
from quantx.domain.enums import OrderStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.idempotency import InMemoryIdempotencyStore
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    ReconciliationPolicy,
    StateSource,
)

CHECKED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
POSITION_POLICY = ReconciliationPolicy(timedelta(seconds=30))


class ScriptedProvider:
    """Deterministic provider double with scripted broker evidence."""

    def __init__(
        self,
        *,
        orders: list[OrderObservation | None] | None = None,
        positions: list[PositionState | None] | None = None,
        accounts: list[AccountFinancialState | None] | None = None,
    ) -> None:
        self._orders = list(orders or [])
        self._positions = list(positions or [])
        self._accounts = list(accounts or [])
        self.order_calls = 0
        self.position_calls = 0
        self.account_calls = 0

    def fetch_broker_order(self, **kwargs: object) -> OrderObservation | None:
        self.order_calls += 1
        if self._orders:
            return self._orders.pop(0)
        return None

    def fetch_broker_position(self, **kwargs: object) -> PositionState | None:
        self.position_calls += 1
        if self._positions:
            return self._positions.pop(0)
        return None

    def fetch_broker_account(self, **kwargs: object) -> AccountFinancialState | None:
        self.account_calls += 1
        if self._accounts:
            return self._accounts.pop(0)
        return None


def _receipt(order_id: UUID) -> ExecutionReceipt:
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=ExecutionOutcome.ACCEPTED,
        order_status=OrderStatus.ACCEPTED,
        executed_at=CHECKED_AT,
        broker_order_id="dhan-1",
        order_id=order_id,
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
    )


def _order(
    order_id: UUID,
    status: OrderLifecycleStatus = OrderLifecycleStatus.FILLED,
    *,
    filled: str = "2",
    broker_order_id: str | None = "dhan-1",
) -> OrderObservation:
    return OrderObservation(order_id, status, "2", filled, broker_order_id)


def _position(
    *,
    observed_at: datetime = CHECKED_AT,
    account: str = "acct-1",
    connection: str = "conn-1",
    quantity: Decimal = Decimal("10"),
) -> PositionState:
    return PositionState(
        AccountId(account),
        BrokerConnectionId(connection),
        "NSE:TCS",
        quantity,
        Decimal("100"),
        observed_at,
        StateSource.BROKER,
    )


def _local_position() -> PositionState:
    return PositionState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "NSE:TCS",
        Decimal("10"),
        Decimal("100"),
        CHECKED_AT,
        StateSource.PAPER,
    )


def _account(*, source: StateSource = StateSource.BROKER) -> AccountFinancialState:
    return AccountFinancialState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        CHECKED_AT,
        source,
        "INR",
        available_cash=Decimal("5000"),
        margin_used=Decimal("0"),
    )


def _refresher(
    provider: ScriptedProvider,
    *,
    max_attempts: int = 3,
    evidence_policy: DefinitiveEvidencePolicy | None = None,
) -> tuple[ReconciliationEvidenceRefresher, ScriptedProvider]:
    return (
        ReconciliationEvidenceRefresher(
            refresh_policy=RefreshPolicy(max_attempts),
            evidence_policy=evidence_policy or DefinitiveEvidencePolicy.order_only(),
        ),
        provider,
    )


def test_already_matched_does_not_refresh() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.definitive is True
    assert outcome.attempts == 0
    assert provider.order_calls == 0
    assert outcome.refreshed_domains == ()


def test_unknown_order_refreshes() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=1)

    refresher.refresh(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert provider.order_calls == 1


def test_future_position_evidence_is_not_accepted_as_fresh() -> None:
    future = _position(observed_at=CHECKED_AT + timedelta(minutes=1))
    from quantx.integrations.reconciliation.positions import (
        PositionReconciler,
        ReconciliationStatus,
    )

    result = PositionReconciler().reconcile(
        _local_position(),
        future,
        checked_at=CHECKED_AT,
        policy=POSITION_POLICY,
    )

    assert result.status is ReconciliationStatus.STALE
    assert "future-dated" in result.message


def test_stale_position_refreshes() -> None:
    order_id = uuid4()
    stale = _position(observed_at=CHECKED_AT - timedelta(minutes=5))
    provider = ScriptedProvider(positions=[_position()])
    refresher, _ = _refresher(
        provider, evidence_policy=DefinitiveEvidencePolicy.order_and_position()
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=stale,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert provider.position_calls == 1
    assert outcome.definitive is True
    assert outcome.result.status is OrderWorkflowStatus.MATCHED


def test_incomplete_position_refreshes() -> None:
    order_id = uuid4()
    provider = ScriptedProvider(positions=[_position()])
    refresher, _ = _refresher(
        provider, evidence_policy=DefinitiveEvidencePolicy.order_and_position()
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert provider.position_calls == 1
    assert outcome.definitive is True


def test_unavailable_account_refreshes() -> None:
    order_id = uuid4()
    provider = ScriptedProvider(accounts=[_account()])
    refresher, _ = _refresher(
        provider,
        evidence_policy=DefinitiveEvidencePolicy(require_position=False, require_account=True),
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_account=_account(source=StateSource.PAPER),
        broker_account=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert provider.account_calls == 1
    assert outcome.definitive is True


def test_refresh_resolves_missing_broker_order_to_matched() -> None:
    order_id = uuid4()
    provider = ScriptedProvider(orders=[_order(order_id)])
    refresher, _ = _refresher(provider)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.attempts == 1
    assert outcome.result.status is OrderWorkflowStatus.MATCHED
    assert outcome.definitive is True
    assert outcome.refreshed_domains == ("order",)


def test_refresh_remains_unknown_when_provider_cannot_resolve() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=2)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.UNKNOWN
    assert outcome.definitive is False


def test_exhausted_budget_preserves_last_unresolved_evidence() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=2)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.attempts == 2
    assert outcome.result.status is OrderWorkflowStatus.UNKNOWN
    assert outcome.definitive is False
    assert "budget" in outcome.reasons[0]


def test_matched_order_with_unresolved_required_position_is_not_definitive() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=1)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.definitive is False


def test_matched_order_and_position_with_unresolved_account_is_not_definitive() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=1)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=_position(),
        local_account=_account(source=StateSource.PAPER),
        broker_account=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.definitive is False


def test_fully_refreshed_evidence_becomes_definitive() -> None:
    order_id = uuid4()
    stale = _position(observed_at=CHECKED_AT - timedelta(minutes=5))
    provider = ScriptedProvider(positions=[_position()], accounts=[_account()])
    refresher, _ = _refresher(provider, evidence_policy=DefinitiveEvidencePolicy.all_required())

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=stale,
        local_account=_account(source=StateSource.PAPER),
        broker_account=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.MATCHED
    assert outcome.definitive is True
    assert set(outcome.refreshed_domains) == {"position", "account"}


def test_account_identity_mismatch_is_rejected() -> None:
    order_id = uuid4()
    foreign = AccountFinancialState(
        AccountId("acct-9"),
        BrokerConnectionId("conn-1"),
        CHECKED_AT,
        StateSource.BROKER,
        "INR",
        available_cash=Decimal("5000"),
    )
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_account=_account(source=StateSource.PAPER),
        broker_account=foreign,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.MISMATCH
    assert outcome.definitive is False
    assert provider.account_calls == 0


def test_connection_identity_mismatch_is_rejected() -> None:
    order_id = uuid4()
    foreign = _position(account="acct-1", connection="conn-9")
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=foreign,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.MISMATCH
    assert outcome.definitive is False


def test_broker_order_identity_mismatch_is_rejected() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id, broker_order_id="dhan-1"),
        broker_order=_order(order_id, broker_order_id="dhan-2"),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.MISMATCH
    assert outcome.definitive is False
    assert provider.order_calls == 0


def test_refreshed_evidence_timestamps_are_preserved() -> None:
    order_id = uuid4()
    fresh_at = CHECKED_AT
    provider = ScriptedProvider(positions=[_position(observed_at=fresh_at)])
    refresher, _ = _refresher(
        provider, evidence_policy=DefinitiveEvidencePolicy.order_and_position()
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        local_position=_local_position(),
        broker_position=_position(observed_at=CHECKED_AT - timedelta(minutes=5)),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.definitive is True
    assert outcome.broker_position is not None
    assert outcome.broker_position.observed_at == fresh_at


def test_provider_call_count_follows_refresh_policy() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=2)

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.attempts == 2
    assert provider.order_calls == 2
    assert outcome.definitive is False


def test_position_refresh_can_use_explicit_instrument_without_existing_position() -> None:
    order_id = uuid4()
    provider = ScriptedProvider(positions=[_position()])
    refresher = ReconciliationEvidenceRefresher(
        refresh_policy=RefreshPolicy(1),
        evidence_policy=DefinitiveEvidencePolicy.order_and_position(),
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        instrument_id="NSE:TCS",
        provider=provider,
    )

    assert provider.position_calls == 1
    assert outcome.result.status is OrderWorkflowStatus.INCOMPLETE
    assert outcome.definitive is False


def test_default_policy_requires_all_evidence_for_definitive() -> None:
    order_id = uuid4()
    provider = ScriptedProvider()
    refresher = ReconciliationEvidenceRefresher(
        refresh_policy=RefreshPolicy(1),
        evidence_policy=DefinitiveEvidencePolicy.all_required(),
    )

    outcome = refresher.refresh(
        _receipt(order_id),
        local_order=_order(order_id),
        broker_order=_order(order_id),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )

    assert outcome.result.status is OrderWorkflowStatus.MATCHED
    assert outcome.definitive is False


def test_definitive_reconciliation_resolves_pending_idempotency() -> None:
    order_id = uuid4()
    receipt = _receipt(order_id)
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)
    outcome = refresher.refresh(
        receipt,
        local_order=_order(order_id),
        broker_order=_order(order_id),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )
    store = InMemoryIdempotencyStore()
    store.reserve(order_id, "fingerprint-a")

    resolved = ReconciliationIdempotencyResolver.resolve(
        outcome,
        receipt,
        request_fingerprint="fingerprint-a",
        idempotency=store,
    )

    assert resolved is True
    decision = store.check(order_id, "fingerprint-a")
    assert decision.existing_receipt_id == receipt.receipt_id
    assert not decision.reservation_pending


def test_non_definitive_reconciliation_leaves_pending_idempotency() -> None:
    order_id = uuid4()
    receipt = _receipt(order_id)
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider, max_attempts=1)
    outcome = refresher.refresh(
        receipt,
        local_order=None,
        broker_order=None,
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )
    store = InMemoryIdempotencyStore()
    store.reserve(order_id, "fingerprint-a")

    resolved = ReconciliationIdempotencyResolver.resolve(
        outcome,
        receipt,
        request_fingerprint="fingerprint-a",
        idempotency=store,
    )

    assert resolved is False
    decision = store.check(order_id, "fingerprint-a")
    assert decision.existing_receipt_id is None
    assert decision.reservation_pending


def test_reconciliation_resolution_rejects_wrong_order_identity() -> None:
    order_id = uuid4()
    receipt = _receipt(order_id)
    other_order_id = uuid4()
    provider = ScriptedProvider()
    refresher, _ = _refresher(provider)
    outcome = refresher.refresh(
        receipt,
        local_order=_order(order_id),
        broker_order=_order(order_id),
        checked_at=CHECKED_AT,
        position_policy=POSITION_POLICY,
        provider=provider,
    )
    other_receipt = _receipt(other_order_id)
    store = InMemoryIdempotencyStore()
    store.reserve(other_order_id, "fingerprint-a")

    import pytest

    with pytest.raises(ValueError, match="order identity"):
        ReconciliationIdempotencyResolver.resolve(
            outcome,
            other_receipt,
            request_fingerprint="fingerprint-a",
            idempotency=store,
        )
