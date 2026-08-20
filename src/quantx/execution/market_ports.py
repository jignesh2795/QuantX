"""Execution ports that require observable market data at execution time."""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest

from .market_data import MarketSnapshot
from .ports import ExecutionReceipt


class MarketDataExecutionPort(Protocol):
    """Execution boundary for simulators/replayers that consume market state."""

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        """Execute using only the supplied point-in-time market snapshot."""
