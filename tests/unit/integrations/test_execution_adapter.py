from datetime import datetime, timezone
from uuid import uuid4

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.execution_adapter import BrokerExecutionAdapter


class FakeSubmission:
    def __init__(self, receipt: ExecutionReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        self.calls += 1
        return self.receipt

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self.receipt

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self.receipt


def test_broker_execution_adapter_delegates_to_submission_plugin() -> None:
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=None,  # type: ignore[arg-type]
        executed_at=datetime.now(timezone.utc),
    )
    submission = FakeSubmission(receipt)
    adapter = BrokerExecutionAdapter(submission)

    # The adapter's contract is delegation; request construction is covered by
    # the execution-request tests and broker plugin contract tests.
    request = object()  # type: ignore[assignment]
    result = adapter.execute(request)

    assert result is receipt
    assert submission.calls == 1
