"""Indian market domain and adapter contracts."""

from .domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    OptionContractSpec,
    ProductType,
)
from .execution_rules import (
    IndiaExecutionRuleEngine,
    IndiaRuleCheck,
    IndiaRuleDecision,
    IndiaRuleResult,
)
from .historical import IndianHistoricalOHLCVNormalizer
from .instrument_catalog import IndianInstrumentCatalog
from .rule_data import IndiaRuleScope, IndiaVenueRuleSnapshot, PriceBandRuleSnapshot

__all__ = [
    "IndiaExecutionRuleEngine",
    "IndiaRuleCheck",
    "IndiaRuleDecision",
    "IndiaRuleResult",
    "IndiaRuleScope",
    "IndiaVenueRuleSnapshot",
    "IndianExchange",
    "IndianHistoricalOHLCVNormalizer",
    "IndianInstrumentCatalog",
    "IndianInstrumentSpec",
    "IndianSegment",
    "OptionContractSpec",
    "PriceBandRuleSnapshot",
    "ProductType",
]
