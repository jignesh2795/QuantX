"""Dispatch approved non-live execution requests to mode-specific adapters.

LIVE submission is intentionally unsupported here because this routing boundary
does not own durable idempotency, persistence, reconciliation, or the trading
gate. LIVE requests must enter through ExecutionOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.policy_verification import MarketPackPolicyVerifier

from .market_data import MarketSnapshot
from .ports import ExecutionReceipt, LiveExecutionPort, MarketDataExecutionPort


@dataclass(frozen=True, slots=True)
class ExecutionDispatchResult:
    """Receipt produced by dispatching an already-approved request."""

    request: ApprovedExecutionRequest
    receipt: ExecutionReceipt


class ExecutionDispatcher:
    """Route approved requests to the adapter matching their execution mode."""

    def __init__(
        self,
        *,
        paper_port: MarketDataExecutionPort | None = None,
        live_port: LiveExecutionPort | None = None,
        policy_verifier: MarketPackPolicyVerifier,
    ) -> None:
        self._paper_port = paper_port
        self._live_port = live_port
        self._policy_verifier = policy_verifier

    def dispatch(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | None = None,
    ) -> ExecutionDispatchResult:
        mode = request.execution_context.execution_mode

        if mode in {
            ExecutionMode.PAPER,
            ExecutionMode.SHADOW,
            ExecutionMode.REPLAY,
        }:
            if self._paper_port is None:
                raise ValueError(f"no paper execution adapter configured for {mode.value} mode")
            # The routed request's product and position-effect claims are
            # authenticated against the deployment's trusted versioned
            # policies before the adapter is called.
            try:
                self._policy_verifier.verify_request(request)
            except Exception as exc:
                raise ValueError(f"request policy verification failed: {exc}") from exc
            if snapshot is None:
                raise ValueError(f"{mode.value} execution requires a market snapshot")
            if snapshot.instrument != request.order.instrument:
                raise ValueError("market snapshot instrument does not match the execution request")
            receipt = self._paper_port.execute(request, snapshot=snapshot)
            return ExecutionDispatchResult(request=request, receipt=receipt)

        if mode is ExecutionMode.LIVE:
            raise ValueError("LIVE dispatch requires ExecutionOrchestrator with durable UnitOfWork")

        raise ValueError(f"execution mode {mode.value} is not dispatchable")


__all__ = ["ExecutionDispatchResult", "ExecutionDispatcher"]
