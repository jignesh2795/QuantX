"""Single execution boundary for paper, replay, shadow, and live modes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionReceipt, MarketDataExecutionPort
from quantx.ports.broker import BrokerPort


class ExecutionDispatchStatus(StrEnum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"


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
    ) -> None:
        self._paper_executor = paper_executor

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

        return ExecutionResult(
            ExecutionDispatchStatus.EXECUTED,
            receipt=broker.submit(request),
        )
