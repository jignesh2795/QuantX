"""Curated public contracts for QuantX.

This module is the supported import boundary for application authors. Its
exports are intentionally smaller than the internal domain and service APIs.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId, Money

__all__ = [
    "AssetClass",
    "Contract",
    "Instrument",
    "InstrumentId",
    "MarketContext",
    "MarketFamily",
    "MarketRegion",
    "Money",
    "OptionType",
]

# All currently exported names are provisional while QuantX is pre-1.0.
# Keep this immutable manifest aligned with __all__ and docs/PUBLIC_API.md.
__api_stability__: Final[Mapping[str, str]] = MappingProxyType(
    {name: "provisional" for name in __all__}
)
