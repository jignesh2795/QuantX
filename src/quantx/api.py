"""Curated provisional public Python API for QuantX.

Only names listed in __all__ are part of the supported import surface.
All currently exported names are provisional; see docs/PUBLIC_API.md for
stability tiers and the pre-1.0 compatibility policy.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

from quantx.domain.clock import Clock, SimulatedClock, SystemClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, PositionEffect, TimeInForce
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.market_data import Candle, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.value_objects import (
    AccountId,
    BrokerConnectionId,
    InstrumentId,
    Money,
    ProductCode,
)
from quantx.ports.market_data import MarketDataPort, MarketDataStore

__all__ = [
    "AccountId",
    "AssetClass",
    "BrokerConnectionId",
    "Candle",
    "Clock",
    "Contract",
    "ExecutionContext",
    "ExecutionMode",
    "Instrument",
    "InstrumentId",
    "MarketContext",
    "MarketDataPort",
    "MarketDataStore",
    "MarketFamily",
    "MarketRegion",
    "Money",
    "OptionType",
    "OrderSide",
    "OrderType",
    "PortfolioId",
    "PositionEffect",
    "ProductCode",
    "Quote",
    "SimulatedClock",
    "StrategyDeploymentId",
    "SystemClock",
    "TimeInForce",
    "TradeIntent",
]

# Keep this immutable manifest aligned with __all__ and docs/PUBLIC_API.md.
# Money is included after the finite-Decimal/currency-safe contract was completed.
__api_stability__: Final[Mapping[str, str]] = MappingProxyType(
    {name: "provisional" for name in __all__}
)
