"""Explicit research data policies for reproducible backtests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PriceSeriesMode(StrEnum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
    EVENT_RECONSTRUCTED = "EVENT_RECONSTRUCTED"


@dataclass(frozen=True, slots=True)
class ResearchDataPolicy:
    """Immutable declaration of how historical data is interpreted."""

    version: str
    price_series_mode: PriceSeriesMode
    adjustment_policy_version: str | None = None
    roll_rule_version: str | None = None
    require_point_in_time_metadata: bool = True
    allow_incomplete_data: bool = False

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("research data policy version must not be empty")
        if self.price_series_mode is not PriceSeriesMode.RAW and not self.adjustment_policy_version:
            raise ValueError("non-raw price series requires an adjustment policy version")
        if self.roll_rule_version is not None and not self.roll_rule_version.strip():
            raise ValueError("roll_rule_version must not be blank")
