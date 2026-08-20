"""Deterministic fill calculations for paper execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .profile import ExecutionProfile, SlippageModel


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    bid: Decimal
    ask: Decimal
    last: Decimal

    def __post_init__(self) -> None:
        if min(self.bid, self.ask, self.last) <= 0:
            raise ValueError("market prices must be positive")
        if self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    price: Decimal
    quantity: Decimal
    fee: Decimal


class FillSimulator:
    """Apply explicit execution assumptions to a market snapshot."""

    def simulate(
        self,
        *,
        side: str,
        quantity: Decimal,
        snapshot: MarketSnapshot,
        profile: ExecutionProfile,
    ) -> SimulatedFill:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        normalized_side = side.upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        reference = snapshot.ask if normalized_side == "BUY" else snapshot.bid
        if profile.slippage_model is SlippageModel.NONE:
            price = reference
        else:
            bps = profile.slippage_bps / Decimal("10000")
            if normalized_side == "BUY":
                price = reference * (Decimal("1") + bps)
            else:
                price = reference * (Decimal("1") - bps)

        fee = price * quantity * profile.fee_rate
        return SimulatedFill(price=price, quantity=quantity, fee=fee)
