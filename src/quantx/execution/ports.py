"""Execution boundary contracts independent of broker implementations."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest

from .receipts.models import ExecutionOutcome, ExecutionReceipt


class ExecutionPort(Protocol):
    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        """Execute an already risk-approved request."""
