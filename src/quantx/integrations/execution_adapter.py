"""Adapter from QuantX execution to a broker submission plugin."""

from __future__ import annotations

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.ports import ExecutionPort, ExecutionReceipt

from .order_submission import BrokerOrderSubmissionPort


class BrokerExecutionAdapter(ExecutionPort):
    """Normalize broker submission behind the core ExecutionPort."""

    def __init__(self, submission: BrokerOrderSubmissionPort) -> None:
        self._submission = submission

    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        if request.execution_context.execution_mode is ExecutionMode.LIVE:
            raise ValueError(
                "LIVE execution requires ExecutionOrchestrator with durable UnitOfWork"
            )
        return self._submission.submit(request)
