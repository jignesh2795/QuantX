"""Pluggable execution-model contracts for deterministic paper simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest

from .market_data import MarketSnapshot


@dataclass(frozen=True, slots=True)
class FillProposal:
    order_id: UUID
    quantity: Decimal
    price: Decimal
    reason: str


class FillModel(ABC):
    @abstractmethod
    def propose_fill(
        self,
        request: ApprovedExecutionRequest,
        snapshot: MarketSnapshot,
    ) -> FillProposal | None:
        """Return a fill proposal, or None when the order cannot fill."""


class QuoteFillModel(FillModel):
    """Simple deterministic quote-aware model.

    Market buys execute from ask and market sells from bid. Limit orders require
    the corresponding quote to cross the limit. Missing required quotes cause
    no fill rather than an invented price.
    """

    def propose_fill(self, request: ApprovedExecutionRequest, snapshot: MarketSnapshot) -> FillProposal | None:
        order = request.order
        if order.order_type is OrderType.MARKET:
            if order.side is OrderSide.BUY:
                price = snapshot.ask
                reason = "market buy at observed ask"
            else:
                price = snapshot.bid
                reason = "market sell at observed bid"
            if price is None:
                return None
            return FillProposal(order.client_order_id, order.quantity, price, reason)

        if order.order_type is OrderType.LIMIT:
            if order.side is OrderSide.BUY:
                if snapshot.ask is None or order.limit_price is None or snapshot.ask > order.limit_price:
                    return None
                return FillProposal(order.client_order_id, order.quantity, snapshot.ask, "limit buy crossed by observed ask")
            if snapshot.bid is None or order.limit_price is None or snapshot.bid < order.limit_price:
                return None
            return FillProposal(order.client_order_id, order.quantity, snapshot.bid, "limit sell crossed by observed bid")

        return None


@dataclass(frozen=True, slots=True)
class SlippageModel:
    """Deterministic basis-point slippage model applied after fill price discovery."""

    basis_points: Decimal = Decimal("0")

    def apply(self, side: OrderSide, price: Decimal) -> Decimal:
        factor = Decimal("1") + (self.basis_points / Decimal("10000"))
        if side is OrderSide.BUY:
            return price * factor
        return price / factor
