"""Deterministic fill calculations for paper execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .profile import ExecutionProfile, LiquidityModel, OrderBookSnapshot, PartialFillPolicy, SlippageModel


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
    remaining_quantity: Decimal = Decimal("0")
    partial: bool = False


class FillSimulator:
    """Apply explicit execution assumptions to a market snapshot/order book."""

    def simulate(
        self,
        *,
        side: str,
        quantity: Decimal,
        snapshot: MarketSnapshot,
        profile: ExecutionProfile,
        order_book: OrderBookSnapshot | None = None,
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

        fill_quantity = quantity
        if profile.liquidity_model is LiquidityModel.TOP_OF_BOOK and order_book is not None:
            levels = order_book.asks if normalized_side == "BUY" else order_book.bids
            top_quantity = levels[0].quantity if levels else Decimal("0")
            fill_quantity = min(quantity, top_quantity)
        elif profile.liquidity_model is LiquidityModel.DEPTH_AWARE and order_book is not None:
            fill_quantity = min(quantity, order_book.available_quantity(normalized_side))

        remaining = quantity - fill_quantity
        if remaining > 0 and profile.partial_fill_policy in {
            PartialFillPolicy.OR_CANCEL,
            PartialFillPolicy.ALL_OR_NONE,
        }:
            fill_quantity = Decimal("0")
            remaining = quantity

        if fill_quantity <= 0:
            return SimulatedFill(
                price=price,
                quantity=Decimal("0"),
                fee=Decimal("0"),
                remaining_quantity=remaining,
            )

        fee = price * fill_quantity * profile.fee_rate
        return SimulatedFill(
            price=price,
            quantity=fill_quantity,
            fee=fee,
            remaining_quantity=remaining,
            partial=remaining > 0,
        )
