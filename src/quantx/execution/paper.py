"""High-fidelity paper execution core with explicit simulation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.domain.clock import Clock
from quantx.domain.deployment import ExecutionMode
from quantx.domain.errors import IdempotencyError, IntegrationError
from quantx.domain.events import OrderFilled, OrderSubmitted
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Fill, OrderStatus

from .market_data import MarketSnapshot
from .models import FillModel, QuoteFillModel, SlippageModel
from .ports import ExecutionOutcome, ExecutionReceipt


# Backward-compatible name for callers that used the earlier paper API.
QuoteSnapshot = MarketSnapshot


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
    """Deterministic, model-driven paper execution engine.

    The engine consumes observed market snapshots and explicit execution models.
    It never fabricates missing prices. The same engine can be used for paper,
    shadow, and replay modes; only the supplied data/model configuration changes.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        profile: PaperSimulationProfile | None = None,
        fill_model: FillModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        self._clock = clock
        self._profile = profile or PaperSimulationProfile()
        self._fill_model = fill_model or QuoteFillModel()
        self._slippage_model = slippage_model or SlippageModel(self._profile.slippage_bps)
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._events: list[object] = []

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
    ) -> ExecutionReceipt:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise PaperExecutionError(
                "paper executor only accepts PAPER, SHADOW, or REPLAY requests"
            )

        if snapshot.instrument != request.order.instrument:
            raise PaperExecutionError("market snapshot instrument does not match the order")

        existing = self._receipts.get(request.order.client_order_id)
        if existing is not None:
            return existing

        proposal = self._fill_model.propose_fill(request, snapshot)
        if proposal is None:
            receipt = ExecutionReceipt(
                request_id=uuid4(),
                client_order_id=request.order.client_order_id,
                outcome=ExecutionOutcome.ACCEPTED,
                order_status=OrderStatus.ACCEPTED,
                fills=(),
                message="order accepted but no fill was available from supplied market data",
                executed_at=self._clock.now(),
                simulated=True,
                model_profile=self._profile.name,
                model_version="paper-core-v0.2",
                assumptions=(
                    f"latency_ms={self._profile.latency_ms}",
                    f"slippage_bps={self._profile.slippage_bps}",
                    f"partial_fill_ratio={self._profile.partial_fill_ratio}",
                    f"fee_bps={self._profile.fee_bps}",
                    "missing_required_liquidity_or_quote_does_not_create_a_fill",
                ),
            )
            self._receipts[request.order.client_order_id] = receipt
            return receipt

        fill_quantity = proposal.quantity * self._profile.partial_fill_ratio
        if fill_quantity <= 0:
            raise PaperExecutionError("simulation produced a non-positive fill quantity")

        price = self._slippage_model.apply(request.order.side, proposal.price)
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
            message=proposal.reason,
            executed_at=now,
            simulated=True,
            model_profile=self._profile.name,
            model_version="paper-core-v0.2",
            assumptions=(
                f"latency_ms={self._profile.latency_ms}",
                f"slippage_bps={self._profile.slippage_bps}",
                f"partial_fill_ratio={self._profile.partial_fill_ratio}",
                f"fee_bps={self._profile.fee_bps}",
                proposal.reason,
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

    def receipt_for(self, client_order_id: UUID) -> ExecutionReceipt | None:
        return self._receipts.get(client_order_id)


__all__ = ["MarketSnapshot", "PaperExecutionEngine", "PaperExecutionError", "PaperSimulationProfile", "QuoteSnapshot"]
