"""Broker order-submission port.

The integration layer translates QuantX execution requests to broker-specific
requests and returns only normalized execution receipts to the core.
"""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.execution.ports import ExecutionReceipt


class BrokerOrderSubmissionPort(Protocol):
    """Minimal contract implemented by broker plugins."""

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        """Submit exactly one normalized execution request."""

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        """Request cancellation and return the normalized broker response."""

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        """Resolve an uncertain broker outcome without resubmitting blindly."""
