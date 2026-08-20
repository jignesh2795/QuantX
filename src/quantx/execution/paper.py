"""High-fidelity paper execution core with explicit simulation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.domain.deployment import ExecutionMode
from quantx.domain.errors import IdempotencyError, IntegrationError
from quantx.domain.events import OrderFilled, OrderSubmitted
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Fill, OrderStatus
from quantx.domain.clock import Clock

from .ports import ExecutionOutcome, ExecutionReceipt


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """Point-in-time quote used by the simulator."""

    timestamp: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None

    def __post_init__(self) -> None:
        if self.bid is None and self.ask is None and self.last is None:
            raise ValueError("quote requires at least one price")
        if self.bid is not None and self.bid <= 0:
            raise ValueError("bid must be positive")
        if self.ask is not None and self.ask <= 0:
            raise ValueError("ask must be positive")
        if self.last is not None and self.last <= 0:
            raise ValueError("last must be positive")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot exceed ask")


class PaperExecutionError(IntegrationError):
    """Raised when a paper execution request cannot be simulated safely."""


@dataclass(frozen=True, slots=True)
class PaperSimulationProfile:
    name: str = "REALISTIC"
    latency_ms: int = 0
    slippage_bps: Decimal = Decimal("0")
    partial_fill_ratio: Decimal = Decimal("1")
    fee_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        if self.slippage_bps < 0 or self.fee_bps < 0:
            raise ValueError("bps values cannot be negative")
        if not Decimal("0") < self.partial_fill_ratio <= Decimal("1"):
            raise ValueError("partial_fill_ratio must be in (0, 1]")


class PaperExecutionEngine:
    """Deterministic paper execution engine.

    The engine deliberately requires an explicit market snapshot or price.
    It never invents market data. More sophisticated models can be plugged in
    later without changing the ExecutionPort contract.
    """

    def __init__(self, *, clock: Clock, profile: PaperSimulationProfile | None = None) -> None:
        self._clock = clock
        self._profile = profile or PaperSimulationProfile()
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._events: list[object] = []

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        quote: QuoteSnapshot,
    ) -> ExecutionReceipt:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise PaperExecutionError("paper executor only accepts PAPER, SHADOW, or REPLAY requests")

        existing = self._receipts.get(request.order.client_order_id)
        if existing is not None:
            if existing.client_order_id != request.order.client_order_id:
                raise IdempotencyError("client order identity collision")
            return existing

        price = self._execution_price(request, quote)
        fill_quantity = request.order.quantity * self._profile.partial_fill_ratio
        status = (
            OrderStatus.FILLED
            if fill_quantity == request.order.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        outcome = (
            ExecutionOutcome.FILLED
            if status is OrderStatus.FILLED
            else ExecutionOutcome.PARTIALLY_FILLED
        )

        now = self._clock.now()
        fill = Fill(
            client_order_id=request.order.client_order_id,
            instrument=request.order.instrument,
            side=request.order.side,
            quantity=fill_quantity,
            price=price,
            filled_at=now,
        )
        receipt = ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=outcome,
            order_status=status,
            fills=(fill,),
            message="paper execution simulated",
            executed_at=now,
            simulated=True,
            model_profile=self._profile.name,
            model_version="paper-core-v0.1",
            assumptions=(
                f"latency_ms={self._profile.latency_ms}",
                f"slippage_bps={self._profile.slippage_bps}",
                f"partial_fill_ratio={self._profile.partial_fill_ratio}",
                f"fee_bps={self._profile.fee_bps}",
            ),
        )
        self._receipts[request.order.client_order_id] = receipt
        self._events.append(
            OrderSubmitted(
                event_id=str(uuid4()),
                occurred_at=now,
                correlation_id=str(request.order.client_order_id),
                order_id=str(request.order.client_order_id),
                venue=request.execution_context.market.venue,
            )
        )
        self._events.append(
            OrderFilled(
                event_id=str(uuid4()),
                occurred_at=now,
                correlation_id=str(request.order.client_order_id),
                order_id=str(request.order.client_order_id),
                fill_id=str(fill.execution_id),
                quantity=fill.quantity,
                price=fill.price,
            )
        )
        return receipt

    def events(self) -> tuple[object, ...]:
        return tuple(self._events)

    def _execution_price(self, request: ApprovedExecutionRequest, quote: QuoteSnapshot) -> Decimal:
        order = request.order
        if order.order_type.value == "MARKET":
            if order.side.value == "BUY":
                base = quote.ask if quote.ask is not None else quote.last
            else:
                base = quote.bid if quote.bid is not None else quote.last
        elif order.order_type.value in {"LIMIT", "STOP_LIMIT"}:
            base = order.limit_price
        else:
            base = quote.last

        if base is None:
            raise PaperExecutionError("required execution price is unavailable")

        sign = Decimal("1") if order.side.value == "BUY" else Decimal("-1")
        slippage = base * self._profile.slippage_bps / Decimal("10000")
        return base + (sign * slippage)
