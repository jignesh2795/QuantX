from datetime import datetime, timezone
from uuid import uuid4

from quantx.domain.orders import OrderStatus
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.execution_adapter import BrokerExecutionAdapter


class FakeSubmission:
    def __init__(self, receipt: ExecutionReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def submit(self, request) -> ExecutionReceipt:
        self.calls += 1
        return self.receipt

    def cancel(self, request) -> ExecutionReceipt:
        return self.receipt

    def reconcile(self, request) -> ExecutionReceipt:
        return self.receipt


def test_broker_execution_adapter_delegates_to_submission_plugin() -> None:
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=uuid4(),
        outcome=ExecutionOutcome.UNKNOWN,
        order_status=OrderStatus.ACCEPTED,
        executed_at=datetime.now(timezone.utc),
    )
    submission = FakeSubmission(receipt)
    adapter = BrokerExecutionAdapter(submission)

    request = object()
    result = adapter.execute(request)  # type: ignore[arg-type]

    assert result is receipt
    assert submission.calls == 1
