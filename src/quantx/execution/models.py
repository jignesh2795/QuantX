"""Pluggable execution-model contracts for deterministic paper simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.market_data import Candle

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
        snapshot: MarketSnapshot | Candle,
    ) -> FillProposal | None:
        """Return a fill proposal, or None when the order cannot fill."""


class QuoteFillModel(FillModel):
    """Simple deterministic quote-aware model.

    Market buys execute from ask and market sells from bid. Limit orders require
    the corresponding quote to cross the limit. Missing required quotes cause
    no fill rather than an invented price.
    """

    def propose_fill(
        self, request: ApprovedExecutionRequest, snapshot: MarketSnapshot | Candle
    ) -> FillProposal | None:
        if not isinstance(snapshot, MarketSnapshot):
            return None
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


class CandleFillModel(FillModel):
    """Deterministic bar-level model (BASIC_BAR) for OHLCV-only evidence.

    Market orders fill at the observed bar close: the only candle reference
    price established by the existing strategy preparation contract. Limit,
    stop, and stop-limit orders cannot be evaluated without intrabar path
    assumptions, so they never propose a fill. Non-candle snapshots are not
    priced. Pricing always uses the bar the strategy observed; no other bar
    is ever read, so no future information can leak into the fill.
    """

    def propose_fill(
        self, request: ApprovedExecutionRequest, snapshot: MarketSnapshot | Candle
    ) -> FillProposal | None:
        if not isinstance(snapshot, Candle):
            return None
        order = request.order
        if order.order_type is not OrderType.MARKET:
            return None
        side = "buy" if order.side is OrderSide.BUY else "sell"
        return FillProposal(
            order.client_order_id,
            order.quantity,
            snapshot.close,
            f"BASIC_BAR market {side} at observed bar close",
        )


class DataAdaptiveFillModel(FillModel):
    """Route fill proposals by observed evidence type without inventing data.

    Quote snapshots use the quote model unchanged; canonical candles use the
    bar model. Anything else is rejected explicitly rather than priced.
    """

    def __init__(
        self,
        *,
        quote_model: FillModel | None = None,
        candle_model: FillModel | None = None,
    ) -> None:
        self._quote_model = quote_model or QuoteFillModel()
        self._candle_model = candle_model or CandleFillModel()

    def propose_fill(
        self, request: ApprovedExecutionRequest, snapshot: MarketSnapshot | Candle
    ) -> FillProposal | None:
        if isinstance(snapshot, Candle):
            return self._candle_model.propose_fill(request, snapshot)
        if isinstance(snapshot, MarketSnapshot):
            return self._quote_model.propose_fill(request, snapshot)
        raise TypeError(f"unsupported market snapshot: {type(snapshot).__name__}")


@dataclass(frozen=True, slots=True)
class SlippageModel:
    """Deterministic basis-point slippage model applied after fill price discovery."""

    basis_points: Decimal = Decimal("0")

    def apply(self, side: OrderSide, price: Decimal) -> Decimal:
        factor = Decimal("1") + (self.basis_points / Decimal("10000"))
        if side is OrderSide.BUY:
            return price * factor
        return price / factor
