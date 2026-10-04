"""Single execution boundary for paper, replay, shadow, and live modes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    PendingExecutionContext,
)
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt, MarketDataExecutionPort
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.session_guard import SessionExecutionGuard
from quantx.execution.trading_gate import TradingGate
from quantx.persistence import UnitOfWork
from quantx.ports.broker import BrokerPort

from .runtime import ApplicationRuntime


class ExecutionDispatchStatus(StrEnum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionDispatchStatus
    receipt: ExecutionReceipt | None = None
    reason: str = ""

    @property
    def executed(self) -> bool:
        return self.status is ExecutionDispatchStatus.EXECUTED


class ExecutionOrchestrator:
    """Fail-closed dispatcher between approved requests and execution adapters."""

    def __init__(
        self,
        *,
        paper_executor: MarketDataExecutionPort | None = None,
        idempotency: IdempotencyStore | None = None,
        unit_of_work: UnitOfWork | None = None,
        trading_gate: TradingGate | None = None,
        application_runtime: ApplicationRuntime | None = None,
        session_guard: SessionExecutionGuard | None = None,
        live_risk_evaluator: Callable[[ApprovedExecutionRequest], RiskResult] | None = None,
    ) -> None:
        self._paper_executor = paper_executor
        self._idempotency = idempotency or InMemoryIdempotencyStore()
        self._unit_of_work = unit_of_work
        self._trading_gate = trading_gate or TradingGate()
        self._trading_gate_explicit = trading_gate is not None
        self._application_runtime = application_runtime
        self._session_guard = session_guard
        self._live_risk_evaluator = live_risk_evaluator

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | None = None,
        broker: BrokerPort | None = None,
    ) -> ExecutionResult:
        mode = request.execution_context.execution_mode

        if mode is ExecutionMode.LIVE:
            if not self._trading_gate_explicit:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires an explicitly configured durable TradingGate",
                )
            if not self._trading_gate.is_durable:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a durable TradingGate",
                )
            if self._application_runtime is None:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires the recovery-backed ApplicationRuntime",
                )
            if not self._application_runtime.started:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a started ApplicationRuntime",
                )

        if not self._trading_gate.allow():
            state = self._trading_gate.state()
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"trading is blocked: {state.reason}",
            )

        if self._session_guard is not None:
            session = self._session_guard.check(mode)
            if not session.allowed:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=session.reason,
                )

        if mode in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            if self._paper_executor is None:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="paper execution adapter is not configured",
                )
            if snapshot is None:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="market snapshot is required for paper/replay execution",
                )
            if snapshot.instrument != request.order.instrument:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="market snapshot instrument does not match execution request",
                )
            return ExecutionResult(
                ExecutionDispatchStatus.EXECUTED,
                receipt=self._paper_executor.execute(request, snapshot=snapshot),
            )

        if mode is not ExecutionMode.LIVE:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"unsupported execution mode: {mode.value}",
            )

        if broker is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="live execution requires a broker adapter",
            )

        connection_id = request.execution_context.broker_connection_id
        if connection_id is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="live execution requires a broker connection",
            )

        connection = broker.connection
        if connection.account_id != request.execution_context.account_id:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker account does not match execution request account",
            )
        if connection.connection_id != connection_id:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker connection does not match execution request connection",
            )
        if not broker.health():
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker connection is not healthy",
            )

        broker_instrument = broker.instrument(request.order.instrument)
        if broker_instrument is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker does not expose the requested canonical instrument",
            )
        if broker_instrument.market != request.execution_context.market:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker instrument market does not match execution request market",
            )

        required_capabilities = request.order.required_capabilities
        if required_capabilities and not broker.capabilities().require(required_capabilities):
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="broker does not support all required execution capabilities",
            )

        unit_of_work = self._unit_of_work
        if unit_of_work is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="live execution requires a durable UnitOfWork",
            )
        if self._live_risk_evaluator is not None:
            try:
                live_risk = self._live_risk_evaluator(request)
            except Exception as exc:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=f"live pre-trade risk evaluation failed closed: {exc}",
                )
            if live_risk.decision is not RiskDecision.APPROVE:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=f"live pre-trade risk rejected the request: {live_risk.reason}",
                )
        return self._execute_live_transactional(request, broker, unit_of_work)

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        lifecycle: ExecutionLifecycle,
        *,
        risk_result: RiskResult,
        snapshot: MarketSnapshot | None = None,
        requested_quantity: Decimal | None = None,
    ) -> ExecutionResult:
        """Continue a partial paper execution through the control plane."""
        mode = request.execution_context.execution_mode
        if not self._trading_gate.allow():
            state = self._trading_gate.state()
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"trading is blocked: {state.reason}",
            )
        if self._session_guard is not None:
            session = self._session_guard.check(mode)
            if not session.allowed:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=session.reason,
                )
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="partial continuation is only supported for paper/replay execution",
            )
        if self._paper_executor is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="paper execution adapter is not configured",
            )
        if snapshot is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="market snapshot is required for partial continuation",
            )
        if snapshot.instrument != request.order.instrument:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="market snapshot instrument does not match execution request",
            )
        continue_partial = getattr(self._paper_executor, "continue_partial", None)
        if not callable(continue_partial):
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="paper execution adapter does not support partial continuation",
            )
        try:
            receipt = continue_partial(
                request,
                lifecycle,
                risk_result=risk_result,
                snapshot=snapshot,
                requested_quantity=requested_quantity,
            )
        except Exception as exc:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=f"partial continuation failed safely: {exc}",
            )
        return ExecutionResult(
            ExecutionDispatchStatus.EXECUTED,
            receipt=receipt,
        )

    def _execute_live_transactional(
        self,
        request: ApprovedExecutionRequest,
        broker: BrokerPort,
        unit_of_work: UnitOfWork,
    ) -> ExecutionResult:
        """Live execution in two scopes so no transaction spans broker submit.

        Scope A commits the PENDING reservation; the broker submission runs
        outside any transaction and outside the trading-gate lock; Scope B
        atomically saves the receipt and completes the reservation.

        R0-B scope: only the safety-critical submit/cancel/reconcile broker
        operations carry bounded timeouts. ``broker.health()`` (checked in
        ``execute`` before this method) never holds the submission permit,
        so an unbounded health probe cannot serialize ``block()``; the
        remaining read-only observations (fund limits, positions, quotes,
        candles) are outside the R0-B bounded-call contract.
        """
        fingerprint = request_fingerprint(request)
        client_order_id = request.order.client_order_id

        # Completed duplicates and existing pending reservations never submit.
        with unit_of_work:
            existing = unit_of_work.idempotency.check(client_order_id, fingerprint)
            if existing.existing_receipt_id is not None:
                authoritative = unit_of_work.receipts.get(existing.existing_receipt_id)
                if authoritative is None:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason=(
                            "persisted receipt is missing for a completed reservation; "
                            "reconciliation is required"
                        ),
                    )
                return ExecutionResult(
                    ExecutionDispatchStatus.EXECUTED,
                    receipt=authoritative,
                    reason=f"idempotent duplicate; receipt={existing.existing_receipt_id}",
                )
            if existing.reservation_pending:
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    reason="submission outcome is unknown; reconciliation is required",
                )
            if existing.operator_resolved:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=(
                        "reservation was explicitly closed by an operator; "
                        "implicit resubmission is prohibited, "
                        "use a new client_order_id for another attempt"
                    ),
                )

        # The permit is acquired before creating the pending reservation.
        # The lock is released BEFORE the broker call so that block() cannot
        # be delayed by a slow/unbounded broker submission.
        # The gate check + reservation creation remain atomic under the lock.
        with self._trading_gate.submission_permit() as permitted:
            if not permitted:
                state = self._trading_gate.state()
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=f"trading is blocked: {state.reason}",
                )

            with unit_of_work:
                pending_context = PendingExecutionContext.from_request(request, fingerprint)
                decision = unit_of_work.idempotency.reserve_or_get(
                    client_order_id,
                    fingerprint,
                    pending_context,
                )
                if decision.existing_receipt_id is not None:
                    authoritative = unit_of_work.receipts.get(decision.existing_receipt_id)
                    if authoritative is None:
                        return ExecutionResult(
                            ExecutionDispatchStatus.UNKNOWN,
                            reason=(
                                "persisted receipt is missing for a completed reservation; "
                                "reconciliation is required"
                            ),
                        )
                    return ExecutionResult(
                        ExecutionDispatchStatus.EXECUTED,
                        receipt=authoritative,
                        reason=f"idempotent duplicate; receipt={decision.existing_receipt_id}",
                    )
                if decision.reservation_pending and not decision.reservation_acquired:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason="submission outcome is unknown; reconciliation is required",
                    )
                if decision.operator_resolved:
                    return ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=(
                            "reservation was explicitly closed by an operator; "
                            "implicit resubmission is prohibited, "
                            "use a new client_order_id for another attempt"
                        ),
                    )
                if not decision.reservation_acquired:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason=(
                            "idempotency reservation was not acquired; "
                            "reconciliation is required"
                        ),
                    )

        # Broker call happens OUTSIDE the trading-gate lock.
        # Timeout is enforced by the broker adapter; any timeout/exception
        # produces UNKNOWN outcome, never REJECTED, and no automatic retry.
        try:
            receipt = broker.submit(request)
        except Exception as exc:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=f"submission outcome is unknown; reconciliation is required: {exc}",
            )
        if receipt.outcome is ExecutionOutcome.UNKNOWN:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                receipt=receipt,
                reason="broker returned an UNKNOWN receipt; reconciliation is required",
            )
        with unit_of_work:
            unit_of_work.receipts.save(receipt)
            try:
                unit_of_work.idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
            except Exception as exc:
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    receipt=receipt,
                    reason=(
                        "submission completed; receipt is durable but idempotency completion "
                        "is uncertain; "
                        f"reconciliation is required: {exc}"
                    ),
                )
        return ExecutionResult(ExecutionDispatchStatus.EXECUTED, receipt=receipt, reason="")
