"""Deterministic paper order matching against an observed market snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .fills import MarketSnapshot
from .order_types import PaperOrderSpec, PaperOrderType


@dataclass(frozen=True, slots=True)
class MatchDecision:
    executable: bool
    reference_price: Decimal | None
    reason: str


class PaperMatcher:
    """Determine whether an order is executable without inventing market data."""

    def evaluate(self, order: PaperOrderSpec, snapshot: MarketSnapshot) -> MatchDecision:
        side = order.side.upper()
        if order.order_type is PaperOrderType.MARKET:
            return MatchDecision(True, snapshot.ask if side == "BUY" else snapshot.bid, "marketable")

        if order.order_type is PaperOrderType.LIMIT:
            if side == "BUY" and order.limit_price >= snapshot.ask:
                return MatchDecision(True, snapshot.ask, "buy limit crosses ask")
            if side == "SELL" and order.limit_price <= snapshot.bid:
                return MatchDecision(True, snapshot.bid, "sell limit crosses bid")
            return MatchDecision(False, None, "limit not marketable")

        if order.stop_price is None:
            return MatchDecision(False, None, "missing stop price")

        triggered = (
            snapshot.last >= order.stop_price if side == "BUY" else snapshot.last <= order.stop_price
        )
        if not triggered:
            return MatchDecision(False, None, "stop not triggered")

        if order.order_type is PaperOrderType.STOP:
            return MatchDecision(True, snapshot.ask if side == "BUY" else snapshot.bid, "stop triggered")

        if side == "BUY" and order.limit_price is not None and snapshot.ask <= order.limit_price:
            return MatchDecision(True, snapshot.ask, "stop-limit triggered and executable")
        if side == "SELL" and order.limit_price is not None and snapshot.bid >= order.limit_price:
            return MatchDecision(True, snapshot.bid, "stop-limit triggered and executable")
        return MatchDecision(False, None, "stop-limit triggered but limit not executable")
