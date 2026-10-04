"""R0-B regression tests: bounded broker timeouts and kill-switch latency."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.execution import (
    ExecutionDispatchStatus,
    ExecutionOrchestrator,
    ExecutionResult,
)
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
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
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.receipts.models import ExecutionOutcome
from quantx.execution.trading_gate import DurableTradingGate
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from quantx.plugins.dhan.host import DhanHostConfig, build_dhan_host_runtime
from quantx.plugins.dhan.models import DhanOrderDetail
from quantx.plugins.dhan.transport import DhanSDKTransport, DhanTimeoutError


def _approving_india_evaluator():
    """India layer is not under test here; approve explicitly to reach it."""

    def approve(request) -> IndiaRuleResult:
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "india compatibility approved for test",
            rule_set_version="test-b3",
            provenance="test-b3",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return approve


class SlowTransport(InMemoryDhanTransport):
    """Transport whose submit/health block on events until released."""

    def __init__(
        self,
        delay_seconds: float = 1.0,
        *,
        block_health: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._delay_seconds = delay_seconds
        self._block_health = block_health
        self._submit_started = threading.Event()
        self._submit_can_proceed = threading.Event()
        self._health_entered = threading.Event()
        self._health_release = threading.Event()

    def submit(self, request, *, timeout: float):
        self._submit_started.set()
        self._submit_can_proceed.wait(timeout=self._delay_seconds + 5.0)
        return super().submit(request, timeout=timeout)

    def health(self) -> bool:
        if not self._block_health:
            return True
        self._health_entered.set()
        assert self._health_release.wait(timeout=10.0)
        return True

    def wait_for_submit_start(self, timeout: float = 5.0) -> bool:
        return self._submit_started.wait(timeout=timeout)

    def wait_for_health_entered(self, timeout: float = 5.0) -> bool:
        return self._health_entered.wait(timeout=timeout)

    def release_submit(self) -> None:
        self._submit_can_proceed.set()

    def release_health(self) -> None:
        self._health_release.set()


class FailingTransport(InMemoryDhanTransport):
    """Transport that raises DhanTimeoutError on submit."""

    def submit(self, request, *, timeout: float):
        # Track the submission before raising
        self._submitted.append(request)
        raise DhanTimeoutError("submit", timeout)


class LateSuccessTransport(InMemoryDhanTransport):
    """Submit times out, but reconcile later observes the broker TRADED."""

    def submit(self, request, *, timeout: float):
        self._submitted.append(request)
        raise DhanTimeoutError("submit", timeout)

    def reconcile(self, correlation_id: str, *, timeout: float) -> DhanOrderDetail:
        return DhanOrderDetail(
            order_id=self.order_id,
            correlation_id=correlation_id,
            order_status="TRADED",
            average_traded_price=Decimal("100"),
            filled_quantity=Decimal("2"),
            exchange_time="2026-01-01 10:00:00",
            update_time="2026-01-01 10:00:00",
        )


class TrackingCloseTransport(InMemoryDhanTransport):
    """Transport that records lifecycle shutdown for host-ownership tests."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _request() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(
    transport: InMemoryDhanTransport,
    *,
    submit_timeout: float = 5.0,
    cancel_timeout: float = 5.0,
    reconcile_timeout: float = 5.0,
) -> DhanBrokerAdapter:
    instrument = _instrument()
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        "NSE_EQ",
    )
    return DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                    product_type="CNC",
                ),
            )
        },
        _transport=transport,
        _submit_timeout=submit_timeout,
        _cancel_timeout=cancel_timeout,
        _reconcile_timeout=reconcile_timeout,
    )


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None):
            from quantx.application.pending_recovery import PendingRecoveryRun
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=None)
    return runtime


def test_gate_block_completes_while_broker_submit_blocked(tmp_path) -> None:
    """R0-B: ``block()`` completes while a broker submit is still blocked.

    Deterministic proof without wall-clock thresholds: the submit thread
    signals entry into the blocked broker call, the block thread must finish
    while the submit thread is still waiting, and only then is the broker
    released.
    """
    transport = SlowTransport(delay_seconds=2.0, response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            india_rule_evaluator=_approving_india_evaluator(),
            application_runtime=_started_runtime(),
        )

        submit_done = threading.Event()
        submit_result: ExecutionDispatchStatus | None = None
        submit_error: Exception | None = None

        def do_submit() -> None:
            nonlocal submit_result, submit_error
            try:
                result = orchestrator.execute(_request(), broker=adapter)
                submit_result = result.status
            except Exception as exc:
                submit_error = exc
            finally:
                submit_done.set()

        block_done = threading.Event()
        block_states: list = []

        def do_block() -> None:
            block_states.append(orchestrator._trading_gate.block("test kill switch"))
            block_done.set()

        submit_thread = threading.Thread(target=do_submit)
        submit_thread.start()
        assert transport.wait_for_submit_start(), "broker submit did not start"

        block_thread = threading.Thread(target=do_block)
        block_thread.start()
        assert block_done.wait(timeout=10.0), "block() did not complete"
        assert not submit_done.is_set(), "block() waited for the broker call"
        assert block_states[0].enabled is False
        assert block_states[0].reason == "test kill switch"

        transport.release_submit()
        assert submit_done.wait(timeout=10.0), "submit thread did not complete"
        submit_thread.join(timeout=10.0)
        block_thread.join(timeout=10.0)
        assert not submit_thread.is_alive()
        assert not block_thread.is_alive()

        assert submit_error is None
        assert submit_result in (
            ExecutionDispatchStatus.EXECUTED,
            ExecutionDispatchStatus.UNKNOWN,
        )
        assert orchestrator._trading_gate.allow() is False
    finally:
        database.close()


def test_slow_health_probe_does_not_serialize_block(tmp_path) -> None:
    """R0-B scope audit: ``health()`` never holds the submission permit.

    A blocked health probe must not serialize ``block()``. Read-only
    observations stay outside the R0-B bounded-call contract.
    """
    transport = SlowTransport(block_health=True, response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            india_rule_evaluator=_approving_india_evaluator(),
            application_runtime=_started_runtime(),
        )

        submit_done = threading.Event()

        def do_submit() -> None:
            try:
                orchestrator.execute(_request(), broker=adapter)
            finally:
                submit_done.set()

        block_done = threading.Event()

        def do_block() -> None:
            orchestrator._trading_gate.block("health-path audit")
            block_done.set()

        submit_thread = threading.Thread(target=do_submit)
        submit_thread.start()
        assert transport.wait_for_health_entered(), "health probe did not start"

        block_thread = threading.Thread(target=do_block)
        block_thread.start()
        assert block_done.wait(timeout=10.0), "block() waited for health probe"
        assert not submit_done.is_set(), "block() serialized behind health()"

        transport.release_health()
        assert submit_done.wait(timeout=10.0)
        submit_thread.join(timeout=10.0)
        block_thread.join(timeout=10.0)
    finally:
        database.close()


def test_blocked_gate_creates_no_reservation_or_submission(tmp_path) -> None:
    """Case A: gate blocked before authorization means no work happens."""
    transport = InMemoryDhanTransport(response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database))
        gate.block("pre-authorized stop")
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=gate,
            application_runtime=_started_runtime(),
            india_rule_evaluator=_approving_india_evaluator(),
        )

        request = _request()
        result = orchestrator.execute(request, broker=adapter)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_authorized_reservation_continues_after_block(tmp_path) -> None:
    """Case B (accepted invariant): auth + reservation pre-block may submit.

    The gate prevents new authorization after blocking; it does not
    retroactively cancel an already-authorized broker submission. This is
    the necessary consequence of decoupling kill-switch latency from
    broker latency.
    """
    transport = SlowTransport(delay_seconds=2.0, response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database))
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=gate,
            application_runtime=_started_runtime(),
            india_rule_evaluator=_approving_india_evaluator(),
        )
        request = _request()
        submit_done = threading.Event()
        submit_result: ExecutionResult | None = None

        def do_submit() -> None:
            nonlocal submit_result
            try:
                submit_result = orchestrator.execute(request, broker=adapter)
            finally:
                submit_done.set()

        submit_thread = threading.Thread(target=do_submit)
        submit_thread.start()
        assert transport.wait_for_submit_start(), "broker submit did not start"

        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is True

        gate.block("post-authorization stop")
        assert gate.allow() is False

        transport.release_submit()
        assert submit_done.wait(timeout=10.0)
        submit_thread.join(timeout=10.0)

        assert submit_result is not None
        assert submit_result.status is ExecutionDispatchStatus.EXECUTED
        assert len(transport.submitted) == 1
        assert gate.allow() is False
    finally:
        database.close()


def test_broker_timeout_produces_unknown_not_rejected(tmp_path) -> None:
    """R0-B: broker timeout must produce UNKNOWN outcome, never REJECTED."""
    transport = FailingTransport(response_status="PENDING")
    adapter = _adapter(transport, submit_timeout=0.1)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            india_rule_evaluator=_approving_india_evaluator(),
            application_runtime=_started_runtime(),
        )

        request = _request()
        result = orchestrator.execute(request, broker=adapter)

        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is None or result.receipt.outcome is ExecutionOutcome.UNKNOWN
        assert "reconciliation is required" in result.reason.lower()
        assert len(transport.submitted) == 1, (
            f"expected 1 submission, got {len(transport.submitted)}"
        )

        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is True
            assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_dhan_adapter_timeout_normalized_to_unknown() -> None:
    """DhanBrokerAdapter normalizes DhanTimeoutError to UNKNOWN receipt."""
    transport = FailingTransport(response_status="PENDING")
    adapter = _adapter(transport, submit_timeout=0.05)

    receipt = adapter.submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status.name == "UNKNOWN"
    assert "timed out" in receipt.message.lower()


def test_call_with_timeout_enforces_bounded_wait() -> None:
    """The real executor wrapper times out a blocked callable via events."""
    transport = object.__new__(DhanSDKTransport)
    executor = ThreadPoolExecutor(max_workers=1)
    transport._executor = executor
    try:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow() -> str:
            entered.set()
            assert release.wait(timeout=10.0)
            finished.set()
            return "late-success"

        with pytest.raises(DhanTimeoutError):
            transport._call_with_timeout(slow, timeout=0.05, operation="submit")
        assert entered.is_set()

        release.set()
        assert finished.wait(timeout=10.0), "worker did not finish after release"
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_late_broker_success_reconciles_without_resubmission(tmp_path) -> None:
    """Timeout is UNKNOWN; a later broker success reconciles, never rejects."""
    transport = LateSuccessTransport(response_status="PENDING")
    adapter = _adapter(transport, submit_timeout=0.05)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            india_rule_evaluator=_approving_india_evaluator(),
            application_runtime=_started_runtime(),
        )
        request = _request()

        result = orchestrator.execute(request, broker=adapter)
        assert result.status is ExecutionDispatchStatus.UNKNOWN

        receipt = adapter.reconcile(request)
        assert receipt.outcome is ExecutionOutcome.FILLED
        assert receipt.order_status.name != "REJECTED"
        assert len(transport.submitted) == 1, (
            f"expected 1 submission, got {len(transport.submitted)}"
        )

        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is True
            assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_host_config_rejects_invalid_timeouts(tmp_path) -> None:
    """DhanHostConfig validation fails closed on invalid timeout values."""
    base_kwargs = {
        "database_path": tmp_path / "quantx.db",
        "account_id": AccountId("acct-1"),
        "connection_id": BrokerConnectionId("conn-1"),
        "market_context_id": "NSE_EQ",
        "instruments": ((_instrument(), DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC")),),
        "transport": InMemoryDhanTransport(),
    }

    valid_timeouts = {
        "submit_timeout_seconds": 5.0,
        "cancel_timeout_seconds": 5.0,
        "reconcile_timeout_seconds": 5.0,
    }

    fields = (
        "submit_timeout_seconds",
        "cancel_timeout_seconds",
        "reconcile_timeout_seconds",
    )
    for field in fields:
        for bad in (0, -1, "invalid", True, False):
            kwargs = {**base_kwargs, **valid_timeouts, field: bad}
            with pytest.raises(ValueError, match=f"{field} must be a positive number"):
                DhanHostConfig(**kwargs)


def test_adapter_rejects_bool_timeouts() -> None:
    """Bool is not an acceptable timeout even though bool is an int."""
    transport = InMemoryDhanTransport()
    for kwargs in (
        {"submit_timeout": True},
        {"cancel_timeout": True},
        {"reconcile_timeout": False},
    ):
        with pytest.raises(ValueError, match="must be a positive number"):
            _adapter(transport, **kwargs)


def test_host_config_accepts_valid_timeouts(tmp_path) -> None:
    """DhanHostConfig accepts valid positive timeout values."""
    config = DhanHostConfig(
        database_path=tmp_path / "quantx.db",
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        market_context_id="NSE_EQ",
        instruments=((_instrument(), DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC")),),
        transport=InMemoryDhanTransport(),
        submit_timeout_seconds=10.0,
        cancel_timeout_seconds=5.0,
        reconcile_timeout_seconds=15.0,
    )

    host = build_dhan_host_runtime(config)
    try:
        assert host.config.submit_timeout_seconds == 10.0
        assert host.config.cancel_timeout_seconds == 5.0
        assert host.config.reconcile_timeout_seconds == 15.0
    finally:
        host.close()


def test_host_close_shuts_down_transport(tmp_path) -> None:
    """Host shutdown owns transport lifecycle; double close stays safe."""
    transport = TrackingCloseTransport()
    config = DhanHostConfig(
        database_path=tmp_path / "quantx.db",
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        market_context_id="NSE_EQ",
        instruments=((_instrument(), DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC")),),
        transport=transport,
        submit_timeout_seconds=5.0,
        cancel_timeout_seconds=5.0,
        reconcile_timeout_seconds=5.0,
    )
    host = build_dhan_host_runtime(config)
    host.close()
    host.close()
    assert transport.close_calls == 2


def test_idempotency_preserved_after_timeout(tmp_path) -> None:
    """After a timeout the PENDING reservation blocks duplicate submission."""
    transport = FailingTransport(response_status="PENDING")
    adapter = _adapter(transport, submit_timeout=0.05)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            india_rule_evaluator=_approving_india_evaluator(),
            application_runtime=_started_runtime(),
        )
        request = _request()

        result1 = orchestrator.execute(request, broker=adapter)
        assert result1.status is ExecutionDispatchStatus.UNKNOWN

        result2 = orchestrator.execute(request, broker=adapter)
        assert result2.status is ExecutionDispatchStatus.UNKNOWN
        assert "unknown" in result2.reason.lower()
        assert len(transport.submitted) == 1, (
            f"expected 1 submission, got {len(transport.submitted)}"
        )

        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is True
            assert decision.existing_receipt_id is None
    finally:
        database.close()
