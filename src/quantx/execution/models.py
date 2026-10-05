"""Pluggable execution-model contracts for deterministic paper simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.market_data import Candle
from quantx.domain.orders import Order

from .market_data import MarketSnapshot


@dataclass(frozen=True, slots=True)
class FillProposal:
    """Deterministic proposed realization of one execution attempt."""

    order_id: UUID
    quantity: Decimal
    price: Decimal
    reason: str
    model_id: str
    model_version: str
    reference_price: Decimal | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal):
            raise TypeError("fill proposal quantity must be a Decimal")
        if self.quantity <= 0:
            raise ValueError("fill proposal quantity must be positive")
        if not isinstance(self.price, Decimal):
            raise TypeError("fill proposal price must be a Decimal")
        if self.price <= 0:
            raise ValueError("fill proposal price must be positive")
        if self.reference_price is not None:
            if not isinstance(self.reference_price, Decimal):
                raise TypeError("fill proposal reference_price must be a Decimal")
            if self.reference_price <= 0:
                raise ValueError("fill proposal reference_price must be positive")
        if not self.reason.strip():
            raise ValueError("fill proposal reason must not be empty")
        if not self.model_id.strip():
            raise ValueError("fill proposal model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("fill proposal model_version must not be empty")


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

    model_id = "QUOTE"
    model_version = "paper-core-v0.3"

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
            return FillProposal(
                order.client_order_id,
                order.quantity,
                price,
                reason,
                self.model_id,
                self.model_version,
                reference_price=price,
                evidence=("reference_price_source=observed_quote",),
            )

        if order.order_type is OrderType.LIMIT:
            if order.side is OrderSide.BUY:
                if (
                    snapshot.ask is None
                    or order.limit_price is None
                    or snapshot.ask > order.limit_price
                ):
                    return None
                return FillProposal(
                    order.client_order_id,
                    order.quantity,
                    snapshot.ask,
                    "limit buy crossed by observed ask",
                    self.model_id,
                    self.model_version,
                    reference_price=snapshot.ask,
                    evidence=("reference_price_source=observed_quote",),
                )
            if (
                snapshot.bid is None
                or order.limit_price is None
                or snapshot.bid < order.limit_price
            ):
                return None
            return FillProposal(
                order.client_order_id,
                order.quantity,
                snapshot.bid,
                "limit sell crossed by observed bid",
                self.model_id,
                self.model_version,
                reference_price=snapshot.bid,
                evidence=("reference_price_source=observed_quote",),
            )

        return None


class StopTrigger(StrEnum):
    """What OHLCV evidence establishes about a stop trigger.

    NOT_TRIGGERED means the stop level was never printed in the bar.
    TRIGGERED means a touch is evidenced and the close confirms a fill price
    that cannot fabricate price improvement. AMBIGUOUS means a touch is
    evidenced but any fill price would require inventing the intrabar path:
    the close sits on the wrong side of the stop, so pricing at the close
    would buy above nothing or sell below nothing that was observed after
    the trigger.
    """

    NOT_TRIGGERED = "NOT_TRIGGERED"
    TRIGGERED = "TRIGGERED"
    AMBIGUOUS = "AMBIGUOUS"


class CandleFillModel(FillModel):
    """Deterministic bar-level model (BASIC_BAR) for OHLCV-only evidence.

    Market orders fill at the observed bar close: the only candle reference
    price established by the existing strategy preparation contract. Limit
    orders use the close-cross rule only: a buy fills when the observed
    close is at or below the limit, a sell when the close is at or above
    the limit, priced at the close. A stop is triggered only when the bar
    range touches the stop level and the close confirms a fill price on the
    triggered side of the stop; a touch without confirmation is ambiguous
    because the intrabar order of events is unknowable, so it never
    proposes a fill. Stop-limit orders always require a post-trigger path
    that OHLCV cannot supply, so they never propose a fill. Non-candle
    snapshots are not priced. Pricing always uses the bar the strategy
    observed; no other bar is ever read, so no future information can leak
    into the fill. An optional candle-volume participation rate bounds the
    proposed quantity by a configured share of the observed bar volume.
    That bound is an explicit simulation assumption, never observed
    liquidity: candle volume is total printed market volume, not executable
    size available to the order.
    """

    model_id = "BASIC_BAR"
    model_version = "basic-bar-v4"

    def __init__(self, *, volume_participation_rate: Decimal | None = None) -> None:
        if volume_participation_rate is not None:
            if not isinstance(volume_participation_rate, Decimal):
                raise TypeError("volume_participation_rate must be a Decimal")
            if not Decimal("0") < volume_participation_rate <= Decimal("1"):
                raise ValueError("volume_participation_rate must be in (0, 1]")
        self._volume_participation_rate = volume_participation_rate

    @staticmethod
    def classify_stop(side: OrderSide, stop_price: Decimal, candle: Candle) -> StopTrigger:
        """Classify a stop trigger from one observed bar without path inference."""
        if side is OrderSide.BUY:
            if candle.high < stop_price:
                return StopTrigger.NOT_TRIGGERED
            if candle.close >= stop_price:
                return StopTrigger.TRIGGERED
            return StopTrigger.AMBIGUOUS
        if candle.low > stop_price:
            return StopTrigger.NOT_TRIGGERED
        if candle.close <= stop_price:
            return StopTrigger.TRIGGERED
        return StopTrigger.AMBIGUOUS

    def _sized_proposal(
        self,
        order: Order,
        snapshot: Candle,
        price: Decimal,
        base_reason: str,
    ) -> FillProposal | None:
        """Apply the configured volume participation cap without touching price."""
        quantity = order.quantity
        reason = base_reason
        if self._volume_participation_rate is not None:
            cap = snapshot.volume * self._volume_participation_rate
            quantity = min(quantity, cap)
            reason = (
                f"{base_reason}; "
                f"volume_participation_rate={self._volume_participation_rate}; "
                f"candle_volume_cap={cap}; "
                "cap is modeled, not observed liquidity"
            )
            if quantity <= 0:
                return None
        return FillProposal(
            order.client_order_id,
            quantity,
            price,
            reason,
            self.model_id,
            self.model_version,
            reference_price=price,
            evidence=("reference_price_source=observed_candle_close",),
        )

    def propose_fill(
        self, request: ApprovedExecutionRequest, snapshot: MarketSnapshot | Candle
    ) -> FillProposal | None:
        if not isinstance(snapshot, Candle):
            return None
        order = request.order
        if order.order_type is OrderType.MARKET:
            side = "buy" if order.side is OrderSide.BUY else "sell"
            return self._sized_proposal(
                order,
                snapshot,
                snapshot.close,
                f"BASIC_BAR market {side} at observed bar close",
            )
        if order.order_type is OrderType.LIMIT:
            if order.limit_price is None:
                return None
            if order.side is OrderSide.BUY:
                if snapshot.close > order.limit_price:
                    return None
                reason = "BASIC_BAR limit buy filled at observed bar close (close-cross)"
            else:
                if snapshot.close < order.limit_price:
                    return None
                reason = "BASIC_BAR limit sell filled at observed bar close (close-cross)"
            return self._sized_proposal(order, snapshot, snapshot.close, reason)
        if order.order_type is OrderType.STOP:
            if order.stop_price is None:
                return None
            trigger = self.classify_stop(order.side, order.stop_price, snapshot)
            if trigger is not StopTrigger.TRIGGERED:
                return None
            side = "buy" if order.side is OrderSide.BUY else "sell"
            return self._sized_proposal(
                order,
                snapshot,
                snapshot.close,
                f"BASIC_BAR stop {side} triggered; filled at observed bar close",
            )
        return None


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
    model_id: str = "paper.fixed_bps_slippage"
    model_version: str = "1"
    provenance: tuple[str, ...] = ("configured_simulation_profile",)

    def __post_init__(self) -> None:
        if not isinstance(self.basis_points, Decimal):
            raise TypeError("basis_points must be a Decimal")
        if self.basis_points < 0:
            raise ValueError("basis_points cannot be negative")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")

    def apply(self, side: OrderSide, price: Decimal) -> Decimal:
        if not isinstance(price, Decimal):
            raise TypeError("price must be a Decimal")
        if price <= 0:
            raise ValueError("price must be positive")
        factor = Decimal("1") + (self.basis_points / Decimal("10000"))
        if side is OrderSide.BUY:
            return price * factor
        return price / factor
