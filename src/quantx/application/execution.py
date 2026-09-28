"""Single execution boundary for paper, replay, shadow, and live modes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionReceipt, MarketDataExecutionPort
from quantx.execution.preconditions import PreconditionsResult, PreconditionsStatus
from quantx.execution.transactions import ExecutionTransactionCoordinator
from quantx.persistence import UnitOfWork
from quantx.ports.broker import BrokerPort


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
    ) -> None:
        self._paper_executor = paper_executor
        self._idempotency = idempotency or InMemoryIdempotencyStore()
        self._unit_of_work = unit_of_work

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | None = None,
        broker: BrokerPort | None = None,
    ) -> ExecutionResult:
        mode = request.execution_context.execution_mode

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
        if unit_of_work is not None:
            return self._execute_live_transactional(request, broker, unit_of_work)

        coordinator = ExecutionTransactionCoordinator(
            idempotency=self._idempotency,
            preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
            submit=broker.submit,
        )
        transaction = coordinator.execute(request)
        if transaction.status is PreconditionsStatus.UNKNOWN:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                receipt=transaction.receipt,
                reason="; ".join(transaction.reasons),
            )
        if transaction.status is not PreconditionsStatus.READY:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                receipt=transaction.receipt,
                reason="; ".join(transaction.reasons),
            )
        return ExecutionResult(
            ExecutionDispatchStatus.EXECUTED,
            receipt=transaction.receipt,
            reason="; ".join(transaction.reasons),
        )

    def _execute_live_transactional(
        self,
        request: ApprovedExecutionRequest,
        broker: BrokerPort,
        unit_of_work: UnitOfWork,
    ) -> ExecutionResult:
        """Live execution in two scopes so no transaction spans broker submit.

        Scope A commits the PENDING reservation; the broker submission runs
        outside any transaction; Scope B atomically saves the receipt and
        completes the reservation. The coordinator is not used here because
        its single execute() call cannot release the transaction mid-flow.
        """
        fingerprint = request_fingerprint(request)
        client_order_id = request.order.client_order_id
        with unit_of_work:
            decision = unit_of_work.idempotency.reserve_or_get(client_order_id, fingerprint)
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
            if not decision.reservation_acquired:
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    reason=("idempotency reservation was not acquired; reconciliation is required"),
                )
        try:
            receipt = broker.submit(request)
        except Exception as exc:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=f"submission outcome is unknown; reconciliation is required: {exc}",
            )
        with unit_of_work:
            unit_of_work.receipts.save(receipt)
            try:
                unit_of_work.idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
            except Exception as exc:
                unit_of_work.rollback()
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    receipt=receipt,
                    reason=(
                        "submission completed but idempotency completion is uncertain; "
                        f"reconciliation is required: {exc}"
                    ),
                )
        return ExecutionResult(ExecutionDispatchStatus.EXECUTED, receipt=receipt, reason="")
