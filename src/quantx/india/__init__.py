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

__all__ = [
    "IndiaExecutionRuleEngine",
    "IndiaRuleCheck",
    "IndiaRuleDecision",
    "IndiaRuleResult",
    "IndianExchange",
    "IndianHistoricalOHLCVNormalizer",
    "IndianInstrumentCatalog",
    "IndianInstrumentSpec",
    "IndianSegment",
    "OptionContractSpec",
    "ProductType",
]
