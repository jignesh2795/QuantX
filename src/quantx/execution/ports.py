"""Canonical execution port contracts.

These protocols are intentionally small. Implementations may be paper, replay,
shadow, or live broker adapters; the domain request and execution receipt stay
broker-neutral.
"""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest

from .market_data import MarketSnapshot
from .receipts.models import ExecutionReceipt


class ExecutionPort(Protocol):
    """Execute an already risk-approved request."""

    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        ...


class MarketDataExecutionPort(Protocol):
    """Execute using only the supplied point-in-time market snapshot."""

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        ...


__all__ = ["ExecutionPort", "MarketDataExecutionPort"]
