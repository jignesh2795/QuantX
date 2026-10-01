"""Compatibility import boundary for historical venue rules.

The canonical rule contract currently lives in ``broker_rules.py``. This module
keeps the previously introduced import path usable while the research package
is consolidated.
"""

from .broker_rules import (
    StaticVenueRuleProvider,
    VenueRuleProvider,
    VenueRuleSnapshot,
)

# Historical name retained for callers that imported VenueRuleContext.
VenueRuleContext = VenueRuleSnapshot

__all__ = [
    "StaticVenueRuleProvider",
    "VenueRuleContext",
    "VenueRuleProvider",
    "VenueRuleSnapshot",
]
