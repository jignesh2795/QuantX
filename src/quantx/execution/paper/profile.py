"""Explicit execution/simulation profiles for deterministic paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class SlippageModel(StrEnum):
    NONE = "NONE"
    FIXED_BPS = "FIXED_BPS"
    SPREAD_AWARE = "SPREAD_AWARE"


class LiquidityModel(StrEnum):
    UNLIMITED = "UNLIMITED"
    TOP_OF_BOOK = "TOP_OF_BOOK"
    DEPTH_AWARE = "DEPTH_AWARE"


class PartialFillPolicy(StrEnum):
    ALLOW = "ALLOW"
    OR_CANCEL = "OR_CANCEL"
    ALL_OR_NONE = "ALL_OR_NONE"


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Versioned, explicit assumptions used by a simulated venue.

    No profile silently invents broker rules. Venue-specific constraints must
    arrive separately as observed/configured integration evidence.
    """

    profile_id: str
    version: str
    slippage_model: SlippageModel = SlippageModel.SPREAD_AWARE
    slippage_bps: Decimal = Decimal("0")
    fee_rate: Decimal = Decimal("0")
    latency_ms: int = 0
    liquidity_model: LiquidityModel = LiquidityModel.TOP_OF_BOOK
    partial_fill_policy: PartialFillPolicy = PartialFillPolicy.ALLOW

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id must not be empty")
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if self.fee_rate < 0:
            raise ValueError("fee_rate cannot be negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
