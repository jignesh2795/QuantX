"""Adapter from QuantX execution to a broker submission plugin."""

from __future__ import annotations

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.ports import ExecutionPort, ExecutionReceipt

from .order_submission import BrokerOrderSubmissionPort


class BrokerExecutionAdapter(ExecutionPort):
    """Normalize broker submission behind the core ExecutionPort."""

    def __init__(self, submission: BrokerOrderSubmissionPort) -> None:
        self._submission = submission

    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self._submission.submit(request)
