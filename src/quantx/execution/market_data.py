"""Compatibility market-data import boundary.

The canonical market-data types live in quantx.domain.market_data. This module
remains as a compatibility path for execution callers during the migration.
"""

from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote

MarketSnapshot = Quote
QuoteSnapshot = MarketSnapshot

__all__ = ["Candle", "MarketDataEvent", "MarketDataType", "Quote", "MarketSnapshot", "QuoteSnapshot"]
