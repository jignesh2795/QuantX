"""Compatibility boundary for the market-data execution port.

The canonical protocol is ``ExecutionPort.MarketDataExecutionPort`` in
``execution.ports``. This module remains temporarily for existing imports.
"""

from .ports import MarketDataExecutionPort

__all__ = ["MarketDataExecutionPort"]
