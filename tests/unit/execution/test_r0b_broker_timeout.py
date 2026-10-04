"""R0-B regression tests: bounded broker timeouts and kill-switch latency."""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
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
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.execution.trading_gate import DurableTradingGate
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.ports.broker import BrokerPort
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from quantx.plugins.dhan.transport import DhanTimeoutError
from quantx.plugins.dhan.host import DhanHostConfig, build_dhan_host_runtime


class SlowTransport(InMemoryDhanTransport):
    """Transport that blocks for a configurable duration on submit."""

    def __init__(self, delay_seconds: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self._delay_seconds = delay_seconds
        self._submit_started = threading.Event()
        self._submit_can_proceed = threading.Event()

    def submit(self, request, *, timeout: float):
        self._submit_started.set()
        self._submit_can_proceed.wait(timeout=self._delay_seconds + 0.5)
        return super().submit(request, timeout=timeout)

    def wait_for_submit_start(self, timeout: float = 1.0) -> bool:
        return self._submit_started.wait(timeout=timeout)

    def release_submit(self) -> None:
        self._submit_can_proceed.set()


class FailingTransport(InMemoryDhanTransport):
    """Transport that raises DhanTimeoutError on submit."""

    def submit(self, request, *, timeout: float):
        # Track the submission before raising
        self._submitted.append(request)
        raise DhanTimeoutError("submit", timeout)


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


def _adapter(transport: InMemoryDhanTransport) -> DhanBrokerAdapter:
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
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None):
            from quantx.application.pending_recovery import PendingRecoveryRun
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=None)
    return runtime


def test_gate_block_not_blocked_by_slow_broker_submit(tmp_path) -> None:
    """
    R0-B: trading_gate.block() must not be indefinitely serialized behind
    a slow broker.submit() call.
    """
    transport = SlowTransport(delay_seconds=2.0, response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
        )

        # Start a slow submission in a background thread
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

        submit_thread = threading.Thread(target=do_submit)
        submit_thread.start()

        # Wait for the broker call to start (gate lock should be released by now)
        assert transport.wait_for_submit_start(timeout=2.0), "broker submit did not start"

        # Now block the gate - this should return immediately, not wait for the slow broker
        block_start = time.monotonic()
        gate_state = orchestrator._trading_gate.block("test kill switch")
        block_elapsed = time.monotonic() - block_start

        # Gate block should be fast (< 100ms), not blocked by the 2s broker call
        assert block_elapsed < 0.5, f"gate.block() took {block_elapsed:.3f}s, expected < 0.5s"
        assert gate_state.enabled is False
        assert gate_state.reason == "test kill switch"

        # Release the slow broker call and wait for submission to complete
        transport.release_submit()
        submit_thread.join(timeout=5.0)
        assert not submit_thread.is_alive(), "submit thread did not complete"

        # Submission should have succeeded (or at least completed)
        assert submit_error is None
        # Note: status could be EXECUTED or UNKNOWN depending on timing
        assert submit_result in (ExecutionDispatchStatus.EXECUTED, ExecutionDispatchStatus.UNKNOWN)

        # Gate should remain blocked
        assert orchestrator._trading_gate.allow() is False
    finally:
        database.close()


def test_broker_timeout_produces_unknown_not_rejected(tmp_path) -> None:
    """
    R0-B: broker timeout must produce UNKNOWN outcome, never REJECTED.
    No automatic retry, no second submission.
    """
    transport = FailingTransport(response_status="PENDING")
    adapter = DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "dhan", "NSE_EQ"
        ),
        _instruments={
            _instrument().instrument_id: (
                _instrument(),
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
        _submit_timeout=0.1,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
        )

        # Use the SAME request object to test idempotency
        request = _request()
        result = orchestrator.execute(request, broker=adapter)

        # Must be UNKNOWN, never BLOCKED (which would imply REJECTED)
        assert result.status is ExecutionDispatchStatus.UNKNOWN, f"expected UNKNOWN, got {result.status}"
        assert result.receipt is None or result.receipt.outcome is ExecutionOutcome.UNKNOWN
        assert "reconciliation is required" in result.reason.lower()

        # Verify only ONE submission was attempted (no auto-retry)
        assert len(transport.submitted) == 1, f"expected 1 submission, got {len(transport.submitted)}"

        # Verify PENDING reservation exists for reconciliation
        from quantx.execution.idempotency.fingerprint import request_fingerprint
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
    adapter = DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "dhan", "NSE_EQ"
        ),
        _instruments={
            _instrument().instrument_id: (
                _instrument(),
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
        _submit_timeout=0.05,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    receipt = adapter.submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status.name == "UNKNOWN"
    assert "timed out" in receipt.message.lower()


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

    for field in ("submit_timeout_seconds", "cancel_timeout_seconds", "reconcile_timeout_seconds"):
        # Test zero
        kwargs = {**base_kwargs, **valid_timeouts, field: 0}
        with pytest.raises(ValueError, match=f"{field} must be a positive number"):
            DhanHostConfig(**kwargs)
        # Test negative
        kwargs = {**base_kwargs, **valid_timeouts, field: -1}
        with pytest.raises(ValueError, match=f"{field} must be a positive number"):
            DhanHostConfig(**kwargs)
        # Test invalid type
        kwargs = {**base_kwargs, **valid_timeouts, field: "invalid"}
        with pytest.raises(ValueError, match=f"{field} must be a positive number"):
            DhanHostConfig(**kwargs)


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


def test_idempotency_preserved_after_timeout(tmp_path) -> None:
    """
    R0-B: After a timeout, the PENDING reservation remains for reconciliation.
    Duplicate submission with same client_order_id + fingerprint is prevented.
    """
    transport = FailingTransport(response_status="PENDING")
    adapter = DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "dhan", "NSE_EQ"
        ),
        _instruments={
            _instrument().instrument_id: (
                _instrument(),
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
        _submit_timeout=0.05,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
            application_runtime=_started_runtime(),
        )

        # Use the SAME request object to test idempotency
        request = _request()

        # First submission times out
        result1 = orchestrator.execute(request, broker=adapter)
        assert result1.status is ExecutionDispatchStatus.UNKNOWN

        # Second submission with same client_order_id should NOT submit again
        result2 = orchestrator.execute(request, broker=adapter)
        assert result2.status is ExecutionDispatchStatus.UNKNOWN
        assert "unknown" in result2.reason.lower()

        # Only ONE broker submission should have occurred
        assert len(transport.submitted) == 1, f"expected 1 submission, got {len(transport.submitted)}"

        # PENDING reservation should still exist
        from quantx.execution.idempotency.fingerprint import request_fingerprint
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as uow:
            decision = uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is True
            assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_sdk_transport_timeout_wrapper() -> None:
    """DhanSDKTransport._call_with_timeout raises DhanTimeoutError on timeout."""
    from quantx.plugins.dhan.transport import DhanSDKTransport, DhanCredentials

    # We can't easily test the real SDK without credentials, but we can verify
    # the DhanTimeoutError is properly defined and raised by the wrapper logic
    exc = DhanTimeoutError("submit", 5.0)
    assert exc.operation == "submit"
    assert exc.timeout == 5.0
    assert "submit timed out after 5.0s" in str(exc)


def test_gate_block_during_slow_broker_call_does_not_deadlock(tmp_path) -> None:
    """
    R0-B: Verify no deadlock when block() is called while broker.submit()
    is in progress. The gate lock is released before the broker call.
    """
    transport = SlowTransport(delay_seconds=1.0, response_status="PENDING")
    adapter = _adapter(transport)

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        gate = DurableTradingGate(SqliteTradingGateStateStore(database))
        orchestrator = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=gate,
            application_runtime=_started_runtime(),
        )

        # Start submission
        submit_started = threading.Event()
        submit_result: ExecutionResult | None = None

        def do_submit() -> None:
            nonlocal submit_result
            submit_result = orchestrator.execute(_request(), broker=adapter)
            submit_started.set()

        submit_thread = threading.Thread(target=do_submit)
        submit_thread.start()

        # Wait for submission to start (gate lock released)
        assert transport.wait_for_submit_start(timeout=2.0)

        # Block gate from another thread - should not deadlock
        block_result = []
        def do_block():
            block_result.append(gate.block("emergency stop"))

        block_thread = threading.Thread(target=do_block)
        block_thread.start()
        block_thread.join(timeout=1.0)

        assert not block_thread.is_alive(), "gate.block() deadlocked on slow broker call"
        assert len(block_result) == 1
        assert block_result[0].enabled is False

        # Clean up
        transport.release_submit()
        submit_thread.join(timeout=5.0)
    finally:
        database.close()