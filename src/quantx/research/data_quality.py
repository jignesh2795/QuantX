"""Compatibility exports for the canonical historical-data quality contract.

Use quantx.research.quality for the authoritative implementation.
"""

from .quality import (
    CompletenessStatus,
    DataIssue,
    DataIssueType,
    DataQualityStatus,
    HistoricalDataQuality,
    HistoricalDataQualityGate,
    assess_candles,
)

__all__ = [
    "CompletenessStatus",
    "DataIssue",
    "DataIssueType",
    "DataQualityStatus",
    "HistoricalDataQuality",
    "HistoricalDataQualityGate",
    "assess_candles",
]
