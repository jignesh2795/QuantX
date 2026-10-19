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
from .market_checks import (
    IndiaCompatCheck,
    IndiaSessionCheck,
    india_market_policy,
    sanitize_rule_reason,
)
from .market_pack import (
    INDIA_EQUITY_COMPATIBILITY_PRODUCT,
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_PRODUCT_SELECTION,
    INDIA_EQUITY_RULE_VERSION,
)
from .rule_data import IndiaRuleScope, IndiaVenueRuleSnapshot, PriceBandRuleSnapshot
from .session_calendar import (
    IndiaSessionCalendar,
    IndiaSessionCalendarSnapshot,
    IndiaSessionDayOverride,
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
    IndiaSessionWindow,
)

__all__ = [
    "INDIA_EQUITY_COMPATIBILITY_PRODUCT",
    "INDIA_EQUITY_MARKET_PACK_ID",
    "INDIA_EQUITY_PRODUCT_SELECTION",
    "INDIA_EQUITY_RULE_VERSION",
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
    "IndiaCompatCheck",
    "IndiaSessionCheck",
    "IndiaSessionCalendar",
    "IndiaSessionCalendarSnapshot",
    "IndiaSessionDayOverride",
    "IndiaSessionDecision",
    "IndiaSessionPermission",
    "IndiaSessionResult",
    "IndiaSessionWindow",
    "india_market_policy",
    "sanitize_rule_reason",
]
