"""Execution port for components that require point-in-time market data."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest

from .market_data import MarketSnapshot
from .receipts.models import ExecutionReceipt


class MarketDataExecutionPort(Protocol):
    """Execution boundary for simulators/replayers consuming market state."""

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        """Execute using only the supplied point-in-time market snapshot."""
