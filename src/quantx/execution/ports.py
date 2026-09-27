"""Canonical execution port contracts."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest
from .market_data import MarketSnapshot
from .receipts.models import ExecutionOutcome, ExecutionReceipt


class ExecutionPort(Protocol):
    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        ...


class MarketDataExecutionPort(Protocol):
    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        ...


__all__ = ["ExecutionPort", "MarketDataExecutionPort", "ExecutionOutcome", "ExecutionReceipt"]
