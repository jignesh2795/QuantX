"""Canonical execution port contracts."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.market_data import Candle

from .market_data import MarketSnapshot
from .receipts.models import ExecutionOutcome, ExecutionReceipt


class ExecutionPort(Protocol):
    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...


class LiveExecutionPort(Protocol):
    """Capability boundary for live execution adapters.

    Concrete broker SDKs must implement this contract in plugins. The core
    owns only the approved-request and receipt semantics; it does not know
    vendor SDK types, credentials, or transport details.

    Implementations are responsible for enforcing broker-specific capability
    checks and translating the canonical request/receipt contracts.
    """

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...


class MarketDataExecutionPort(Protocol):
    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | Candle,
    ) -> ExecutionReceipt: ...


__all__ = [
    "ExecutionPort",
    "LiveExecutionPort",
    "MarketDataExecutionPort",
    "ExecutionOutcome",
    "ExecutionReceipt",
]
