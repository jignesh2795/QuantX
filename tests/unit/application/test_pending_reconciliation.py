"""Integration tests for pending-execution reconciliation over real SQLite."""

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier, Lock, Thread

import pytest

from quantx.application.evidence_refresh import DefinitiveEvidencePolicy
from quantx.application.pending_reconciliation import reconcile_pending_execution
from quantx.application.pending_recovery import PendingExecutionRecoveryRunner
from quantx.application.reconciliation import OrderWorkflowStatus
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.preconditions.models import PreconditionsResult, PreconditionsStatus
from quantx.execution.transactions.coordinator import ExecutionTransactionCoordinator
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    StateSource,
)
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteIdempotencyStore,
    SqliteReceiptRepository,
    SqliteUnitOfWork,
)

CHECKED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class ScriptedProvider:
    def __init__(self, *, orders=None, positions=None, accounts=None) -> None:
        self._orders = list(orders or [])
        self._positions = list(positions or [])
        self._accounts = list(accounts or [])
        self.order_calls = 0
        self.position_calls = 0
        self.account_calls = 0

    def fetch_broker_order(self, **kwargs):
        self.order_calls += 1
        if self._orders:
            return self._orders.pop(0)
        return None

    def fetch_broker_position(self, **kwargs):
        self.position_calls += 1
        if self._positions:
            return self._positions.pop(0)
        return None

    def fetch_broker_account(self, **kwargs):
        self.account_calls += 1
        if self._accounts:
            return self._accounts.pop(0)
        return None


class ExplodingProvider:
    def fetch_broker_order(self, **kwargs):
        raise RuntimeError("broker unavailable")

    def fetch_broker_position(self, **kwargs):
        raise RuntimeError("broker unavailable")

    def fetch_broker_account(self, **kwargs):
        raise RuntimeError("broker unavailable")


def _request() -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    return ApprovedExecutionRequest(
        order,
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _observation(order_id, status, *, filled="0"):
    return OrderObservation(order_id, status, "2", filled, "dhan-1")


def _fill(request, quantity="2"):
    return Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal(quantity),
        price=Decimal("100"),
        filled_at=CHECKED_AT,
    )


def _database_and_uow(tmp_path):
    database = SqliteDatabase(tmp_path / "quantx.db")
    return database, SqliteUnitOfWork(database)


def test_definitive_positive_resolution(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fp-a",
    )
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        broker_order = _observation(order_id, OrderLifecycleStatus.FILLED, filled="2")
        provider = ScriptedProvider(orders=[broker_order])

        outcome = reconcile_pending_execution(
            request,
            fingerprint="fp-a",
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert outcome.definitive
        assert provider.order_calls >= 1
        persisted = SqliteReceiptRepository(database).get_by_client_order(order_id)
        assert persisted is not None
        assert persisted.outcome.value == "FILLED"
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.existing_receipt_id == persisted.receipt_id
        assert not decision.reservation_pending

        def submit(_):
            raise AssertionError("reconciliation must not submit")

        duplicate = ExecutionTransactionCoordinator(
            idempotency=SqliteIdempotencyStore(database),
            preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
            submit=submit,
            receipt_repository=SqliteReceiptRepository(database),
        ).execute(request)
        assert duplicate.status is PreconditionsStatus.READY
    finally:
        database.close()


def test_non_definitive_evidence_leaves_pending(tmp_path) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        provider = ScriptedProvider(orders=[])

        outcome = reconcile_pending_execution(
            request,
            fingerprint="fp-a",
            local_order=None,
            broker_order=None,
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert not outcome.definitive
        assert provider.order_calls >= 1
        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_mismatch_leaves_pending_without_terminal_state(tmp_path) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        provider = ScriptedProvider(orders=[])

        outcome = reconcile_pending_execution(
            request,
            fingerprint="fp-a",
            local_order=_observation(order_id, OrderLifecycleStatus.SUBMITTED),
            broker_order=_observation(order_id, OrderLifecycleStatus.CANCELLED),
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert not outcome.definitive
        assert outcome.result.status is OrderWorkflowStatus.MISMATCH
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.reservation_pending
        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
    finally:
        database.close()


def test_fingerprint_mismatch_rejected(tmp_path) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )

        with pytest.raises(ValueError, match="different request"):
            reconcile_pending_execution(
                request,
                fingerprint="fp-b",
                local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
                broker_order=None,
                fills=(_fill(request),),
                provider=provider,
                unit_of_work=unit_of_work,
                checked_at=CHECKED_AT,
                evidence_policy=DefinitiveEvidencePolicy.order_only(),
            )

        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.reservation_pending
    finally:
        database.close()


def test_already_complete_preserves_immutable_semantics(tmp_path) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )
        first = reconcile_pending_execution(
            request,
            fingerprint="fp-a",
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )
        assert first.definitive
        original = SqliteReceiptRepository(database).get_by_client_order(order_id)
        assert original is not None

        with pytest.raises(ValueError, match="non-pending"):
            reconcile_pending_execution(
                request,
                fingerprint="fp-a",
                local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
                broker_order=None,
                fills=(_fill(request),),
                provider=ScriptedProvider(
                    orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
                ),
                unit_of_work=unit_of_work,
                checked_at=CHECKED_AT,
                evidence_policy=DefinitiveEvidencePolicy.order_only(),
            )

        assert SqliteReceiptRepository(database).get_by_client_order(order_id) == original
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.existing_receipt_id == original.receipt_id
    finally:
        database.close()


def test_resolution_failure_leaves_no_partial_state(tmp_path, monkeypatch) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )

        def boom(*args, **kwargs):
            raise RuntimeError("resolution unavailable")

        monkeypatch.setattr(unit_of_work.idempotency, "resolve_pending", boom)
        with pytest.raises(RuntimeError, match="resolution unavailable"):
            reconcile_pending_execution(
                request,
                fingerprint="fp-a",
                local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
                broker_order=None,
                fills=(_fill(request),),
                provider=provider,
                unit_of_work=unit_of_work,
                checked_at=CHECKED_AT,
                evidence_policy=DefinitiveEvidencePolicy.order_only(),
            )

        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_evidence_failure_leaves_pending(tmp_path) -> None:
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        unit_of_work.idempotency.reserve_or_get(order_id, "fp-a")

        with pytest.raises(RuntimeError, match="broker unavailable"):
            reconcile_pending_execution(
                request,
                fingerprint="fp-a",
                local_order=None,
                broker_order=None,
                provider=ExplodingProvider(),
                unit_of_work=unit_of_work,
                checked_at=CHECKED_AT,
                evidence_policy=DefinitiveEvidencePolicy.order_only(),
            )

        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        decision = SqliteIdempotencyStore(database).check(order_id, "fp-a")
        assert decision.reservation_pending
    finally:
        database.close()


def test_reconciliation_never_submits_to_broker() -> None:
    parameters = inspect.signature(reconcile_pending_execution).parameters
    assert "submit" not in parameters
    assert "broker" not in parameters
    assert "provider" in parameters

def test_pending_context_round_trip_reconstructs_recovery_request() -> None:
    request = _request()
    fingerprint = request_fingerprint(request)
    context = PendingExecutionContext.from_request(request, fingerprint)

    restored = PendingExecutionContext.from_json(context.to_json())
    recovery_request = restored.to_recovery_request()

    assert restored.request_fingerprint == fingerprint
    assert recovery_request.order == request.order
    assert recovery_request.execution_context == request.execution_context
    assert recovery_request.correlation_id == request.correlation_id


def test_pending_live_reservation_survives_restart_and_reconciles(tmp_path) -> None:
    request = _request()
    order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)

    database_a, unit_of_work_a = _database_and_uow(tmp_path)
    try:
        decision = unit_of_work_a.idempotency.reserve_or_get(
            order_id,
            fingerprint,
            PendingExecutionContext.from_request(request, fingerprint),
        )
        assert decision.reservation_acquired
    finally:
        database_a.close()

    database_b, unit_of_work_b = _database_and_uow(tmp_path)
    try:
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )
        blocked = ExecutionTransactionCoordinator(
            idempotency=SqliteIdempotencyStore(database_b),
            preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
            submit=lambda _: (_ for _ in ()).throw(
                AssertionError("pending execution must not resubmit after restart")
            ),
            receipt_repository=SqliteReceiptRepository(database_b),
        ).execute(request)
        assert blocked.status is PreconditionsStatus.UNKNOWN
        assert len(SqliteIdempotencyStore(database_b).list_pending_contexts()) == 1

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=provider,
            unit_of_work=unit_of_work_b,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        assert outcome.definitive
        persisted = SqliteReceiptRepository(database_b).get_by_client_order(order_id)
        assert persisted is not None
        decision = SqliteIdempotencyStore(database_b).check(order_id, fingerprint)
        assert decision.pending_context is not None
        assert decision.pending_context.order == request.order
        assert decision.pending_context.execution_context == request.execution_context
        assert decision.existing_receipt_id == persisted.receipt_id
        assert not decision.reservation_pending
    finally:
        database_b.close()


def test_pending_recovery_runner_resolves_with_default_all_required_evidence(tmp_path) -> None:
    request = _request()
    order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        unit_of_work.idempotency.reserve_or_get(
            order_id,
            fingerprint,
            PendingExecutionContext.from_request(request, fingerprint),
        )
        broker_order = OrderObservation(
            order_id,
            OrderLifecycleStatus.FILLED,
            "2",
            "2",
            "dhan-1",
            request.execution_context.account_id,
            request.execution_context.broker_connection_id,
        )
        broker_position = PositionState(
            request.execution_context.account_id,
            request.execution_context.broker_connection_id,
            "NSE:TCS",
            Decimal("10"),
            Decimal("100"),
            CHECKED_AT,
            StateSource.BROKER,
        )
        broker_account = AccountFinancialState(
            request.execution_context.account_id,
            request.execution_context.broker_connection_id,
            CHECKED_AT,
            StateSource.BROKER,
            "INR",
            available_cash=Decimal("5000"),
            margin_used=Decimal("0"),
        )
        provider = ScriptedProvider(
            orders=[broker_order],
            positions=[broker_position],
            accounts=[broker_account],
        )

        local_position = PositionState(
            request.execution_context.account_id,
            request.execution_context.broker_connection_id,
            "NSE:TCS",
            Decimal("10"),
            Decimal("100"),
            CHECKED_AT,
            StateSource.PAPER,
        )
        local_account = AccountFinancialState(
            request.execution_context.account_id,
            request.execution_context.broker_connection_id,
            CHECKED_AT,
            StateSource.PAPER,
            "INR",
            available_cash=Decimal("5000"),
            margin_used=Decimal("0"),
        )
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=lambda _: provider,
            local_order_provider=lambda recovered: OrderObservation(
                recovered.order.client_order_id,
                OrderLifecycleStatus.FILLED,
                "2",
                "2",
                "dhan-1",
            ),
            local_position_provider=lambda _: local_position,
            local_account_provider=lambda _: local_account,
            fill_provider=lambda recovered, _: (_fill(recovered),),
        )

        report = runner.run(checked_at=CHECKED_AT)

        assert report.attempted == 1
        assert report.resolved == 1
        assert report.pending == 0
        assert report.failed == 0
    finally:
        database.close()


def test_pending_recovery_runner_resolves_after_restart(tmp_path) -> None:
    request = _request()
    order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)
    database_a, unit_of_work_a = _database_and_uow(tmp_path)
    try:
        decision = unit_of_work_a.idempotency.reserve_or_get(
            order_id,
            fingerprint,
            PendingExecutionContext.from_request(request, fingerprint),
        )
        assert decision.reservation_acquired
    finally:
        database_a.close()

    database_b, unit_of_work_b = _database_and_uow(tmp_path)
    try:
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work_b,
            provider_resolver=lambda _: provider,
            local_order_provider=lambda recovered: _observation(
                recovered.order.client_order_id,
                OrderLifecycleStatus.FILLED,
                filled="2",
            ),
            fill_provider=lambda recovered, _: (_fill(recovered),),
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        report = runner.run(checked_at=CHECKED_AT)

        assert report.attempted == 1
        assert report.resolved == 1
        assert report.pending == 0
        assert report.failed == 0
        assert provider.order_calls >= 1
        assert len(SqliteIdempotencyStore(database_b).list_pending_contexts()) == 0
        decision = SqliteIdempotencyStore(database_b).check(order_id, fingerprint)
        assert decision.existing_receipt_id is not None
    finally:
        database_b.close()


def test_pending_recovery_runner_concurrent_passes_resolve_once(tmp_path) -> None:
    request = _request()
    order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        unit_of_work.idempotency.reserve_or_get(
            order_id,
            fingerprint,
            PendingExecutionContext.from_request(request, fingerprint),
        )
    finally:
        database.close()

    database_a = SqliteDatabase(tmp_path / "quantx.db")
    database_b = SqliteDatabase(tmp_path / "quantx.db")
    unit_of_work_a = SqliteUnitOfWork(database_a)
    unit_of_work_b = SqliteUnitOfWork(database_b)
    barrier = Barrier(2)
    lock = Lock()
    calls = {"orders": 0}

    class ConcurrentProvider:
        def fetch_broker_order(self, **kwargs):
            with lock:
                calls["orders"] += 1
            barrier.wait(timeout=5)
            return OrderObservation(
                order_id,
                OrderLifecycleStatus.FILLED,
                "2",
                "2",
                "dhan-1",
            )

        def fetch_broker_position(self, **kwargs):
            return None

        def fetch_broker_account(self, **kwargs):
            return None

    provider = ConcurrentProvider()

    def make_runner(uow):
        return PendingExecutionRecoveryRunner(
            unit_of_work=uow,
            provider_resolver=lambda _: provider,
            local_order_provider=lambda recovered: OrderObservation(
                recovered.order.client_order_id,
                OrderLifecycleStatus.FILLED,
                "2",
                "2",
                "dhan-1",
            ),
            fill_provider=lambda recovered, _: (_fill(recovered),),
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

    runners = (make_runner(unit_of_work_a), make_runner(unit_of_work_b))
    reports = [None, None]

    def run(index):
        reports[index] = runners[index].run(checked_at=CHECKED_AT)

    threads = [Thread(target=run, args=(0,)), Thread(target=run, args=(1,))]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)
        assert calls["orders"] == 2
        assert sum(report.resolved for report in reports if report is not None) == 1
        assert sum(report.failed for report in reports if report is not None) == 1
        with database_a.transaction() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM receipts WHERE client_order_id = ?",
                (str(order_id),),
            ).fetchone()[0]
        assert count == 1
        assert len(SqliteIdempotencyStore(database_a).list_pending_contexts()) == 0
    finally:
        database_a.close()
        database_b.close()


def test_pending_recovery_runner_isolates_malformed_context(tmp_path) -> None:
    request = _request()
    order_id = request.order.client_order_id
    fingerprint = request_fingerprint(request)
    database, unit_of_work = _database_and_uow(tmp_path)
    malformed_order_id = str(request.order.client_order_id)
    while malformed_order_id == str(order_id):
        malformed_order_id = str(__import__("uuid").uuid4())
    try:
        unit_of_work.idempotency.reserve_or_get(
            order_id,
            fingerprint,
            PendingExecutionContext.from_request(request, fingerprint),
        )
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO idempotency_reservations "
                "(client_order_id, fingerprint, receipt_id, created_at, completed_at, "
                "pending_context_json) VALUES (?, ?, NULL, ?, NULL, ?)",
                (
                    malformed_order_id,
                    "malformed-fingerprint",
                    CHECKED_AT.isoformat(),
                    "{malformed-json",
                ),
            )
        provider = ScriptedProvider(
            orders=[_observation(order_id, OrderLifecycleStatus.FILLED, filled="2")]
        )
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=lambda _: provider,
            local_order_provider=lambda recovered: _observation(
                recovered.order.client_order_id,
                OrderLifecycleStatus.FILLED,
                filled="2",
            ),
            fill_provider=lambda recovered, _: (_fill(recovered),),
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        report = runner.run(checked_at=CHECKED_AT)

        assert report.attempted == 2
        assert report.resolved == 1
        assert report.pending == 0
        assert report.failed == 1
        malformed = next(
            result for result in report.results if result.client_order_id == malformed_order_id
        )
        assert malformed.error is not None
        assert "invalid pending execution context" in malformed.error
        assert len(SqliteIdempotencyStore(database).list_pending_contexts()) == 0
        with database.transaction() as connection:
            row = connection.execute(
                "SELECT receipt_id, pending_context_json "
                "FROM idempotency_reservations WHERE client_order_id = ?",
                (malformed_order_id,),
            ).fetchone()
        assert row[0] is None
        assert row[1] == "{malformed-json"
    finally:
        database.close()


def test_pending_recovery_runner_isolates_failed_context(tmp_path) -> None:
    request_ok = _request()
    request_bad = _request()
    fingerprint_ok = request_fingerprint(request_ok)
    fingerprint_bad = request_fingerprint(request_bad)
    database, unit_of_work = _database_and_uow(tmp_path)
    try:
        unit_of_work.idempotency.reserve_or_get(
            request_ok.order.client_order_id,
            fingerprint_ok,
            PendingExecutionContext.from_request(request_ok, fingerprint_ok),
        )
        unit_of_work.idempotency.reserve_or_get(
            request_bad.order.client_order_id,
            fingerprint_bad,
            PendingExecutionContext.from_request(request_bad, fingerprint_bad),
        )
        good_provider = ScriptedProvider(
            orders=[
                _observation(
                    request_ok.order.client_order_id,
                    OrderLifecycleStatus.FILLED,
                    filled="2",
                )
            ]
        )

        def provider_for(request):
            if request.order.client_order_id == request_ok.order.client_order_id:
                return good_provider
            return ExplodingProvider()

        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=provider_for,
            local_order_provider=lambda recovered: _observation(
                recovered.order.client_order_id,
                OrderLifecycleStatus.FILLED,
                filled="2",
            ),
            fill_provider=lambda recovered, _: (_fill(recovered),),
            evidence_policy=DefinitiveEvidencePolicy.order_only(),
        )

        report = runner.run(checked_at=CHECKED_AT)

        assert report.attempted == 2
        assert report.resolved == 1
        assert report.pending == 0
        assert report.failed == 1
        assert len(SqliteIdempotencyStore(database).list_pending_contexts()) == 1
        bad_decision = SqliteIdempotencyStore(database).check(
            request_bad.order.client_order_id, fingerprint_bad
        )
        assert bad_decision.reservation_pending
    finally:
        database.close()
