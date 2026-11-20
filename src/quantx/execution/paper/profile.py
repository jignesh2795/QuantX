"""Explicit execution/simulation profiles for deterministic paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from quantx.execution.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
)


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
    """Versioned assumptions used by a simulated venue."""

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
        for name, value in (("slippage_bps", self.slippage_bps), ("fee_rate", self.fee_rate)):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionProfileChargeAdapter:
    """Adapt the legacy fractional fee profile to the canonical charge contract."""

    profile: ExecutionProfile

    @property
    def model_id(self) -> str:
        return f"paper.execution_profile.{self.profile.profile_id}"

    @property
    def model_version(self) -> str:
        return self.profile.version

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        amount = context.transaction_value * self.profile.fee_rate
        return ChargeBreakdown(
            currency=context.currency,
            components=(ChargeComponent("legacy_fee", amount),),
            model_id=self.model_id,
            model_version=self.model_version,
            provenance=(
                "legacy_execution_profile",
                f"profile_id:{self.profile.profile_id}",
                f"fee_rate:{self.profile.fee_rate}",
            ),
        )


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("order-book levels must be positive")


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    observed_at_ns: int

    def __post_init__(self) -> None:
        if self.observed_at_ns < 0:
            raise ValueError("observed_at_ns cannot be negative")

    def available_quantity(self, side: str) -> Decimal:
        levels = self.asks if side.upper() == "BUY" else self.bids if side.upper() == "SELL" else ()
        return sum((level.quantity for level in levels), Decimal("0"))
