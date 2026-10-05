"""Deterministic paper execution with explicit simulation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.domain.clock import Clock
from quantx.domain.deployment import ExecutionMode
from quantx.domain.enums import OrderStatus
from quantx.domain.errors import IntegrationError
from quantx.domain.events import OrderFilled, OrderSubmitted
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.market_data import Candle
from quantx.domain.orders import Fill
from quantx.domain.risk import RiskResult
from quantx.persistence import ReceiptRepository

from .charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeModel,
    PercentageBpsChargeModel,
)
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore, request_fingerprint
from .market_data import MarketSnapshot
from .models import FillModel, QuoteFillModel, SlippageModel
from .ports import ExecutionOutcome, ExecutionReceipt
from .receipts.lifecycle import ExecutionLifecycle

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
    charge_model: ChargeModel | None = None

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        if not isinstance(self.slippage_bps, Decimal):
            raise TypeError("slippage_bps must be a Decimal")
        if not isinstance(self.fee_bps, Decimal):
            raise TypeError("fee_bps must be a Decimal")
        if self.slippage_bps < 0 or self.fee_bps < 0:
            raise ValueError("bps values cannot be negative")
        if self.charge_model is not None and self.fee_bps != Decimal("0"):
            raise ValueError("charge_model cannot be combined with non-zero fee_bps")
        if not Decimal("0") < self.partial_fill_ratio <= Decimal("1"):
            raise ValueError("partial_fill_ratio must be in (0, 1]")


class PaperExecutionEngine:
    def __init__(
        self,
        *,
        clock: Clock,
        profile: PaperSimulationProfile | None = None,
        fill_model: FillModel | None = None,
        slippage_model: SlippageModel | None = None,
        idempotency_store: IdempotencyStore | None = None,
        receipt_repository: ReceiptRepository | None = None,
    ) -> None:
        self._clock = clock
        self._profile = profile or PaperSimulationProfile()
        self._fill_model = fill_model or QuoteFillModel()
        self._slippage_model = slippage_model or SlippageModel(self._profile.slippage_bps)
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._receipt_repository = receipt_repository
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._events: list[object] = []

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | Candle,
    ) -> ExecutionReceipt:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise PaperExecutionError(
                "paper executor only accepts PAPER, SHADOW, or REPLAY requests"
            )
        if snapshot.instrument != request.order.instrument:
            raise PaperExecutionError("market snapshot instrument does not match the order")

        client_order_id = request.order.client_order_id
        fingerprint = request_fingerprint(request)
        reservation = self._idempotency.reserve_or_get(client_order_id, fingerprint)
        if reservation.existing_receipt_id is not None:
            if self._receipt_repository is not None:
                authoritative = self._receipt_repository.get(reservation.existing_receipt_id)
                if authoritative is None:
                    raise PaperExecutionError(
                        "idempotency store references a completed receipt that is "
                        "not available in the authoritative repository"
                    )
                return authoritative
            existing = self._receipts.get(client_order_id)
            if existing is None:
                raise PaperExecutionError(
                    "idempotency store references a completed receipt that is not available"
                )
            return existing
        if not reservation.reservation_acquired:
            raise PaperExecutionError("submission is already pending and requires reconciliation")

        proposal = self._fill_model.propose_fill(request, snapshot)
        if proposal is None:
            receipt = ExecutionReceipt(
                request_id=uuid4(),
                client_order_id=request.order.client_order_id,
                outcome=ExecutionOutcome.ACCEPTED,
                order_status=OrderStatus.ACCEPTED,
                executed_at=self._clock.now(),
                fills=(),
                message="order accepted but no fill was available from supplied market data",
                simulated=True,
                source="paper",
                account_id=request.execution_context.account_id,
                connection_id=request.execution_context.broker_connection_id,
                correlation_id=request.correlation_id,
                order_id=request.order.client_order_id,
                order_quantity=request.order.quantity,
                model_profile=self._profile.name,
                model_version="paper-core-v0.3",
                assumptions=(
                    f"latency_ms={self._profile.latency_ms}",
                    f"slippage_bps={self._profile.slippage_bps}",
                    f"partial_fill_ratio={self._profile.partial_fill_ratio}",
                    f"fee_bps={self._profile.fee_bps}",
                    "missing_required_liquidity_or_quote_does_not_create_a_fill",
                ),
            )
            if self._receipt_repository is not None:
                self._receipt_repository.save(receipt)
            self._receipts[client_order_id] = receipt
            self._idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
            return receipt

        fill_quantity = proposal.quantity * self._profile.partial_fill_ratio
        if fill_quantity <= 0:
            raise PaperExecutionError("simulation produced a non-positive fill quantity")
        if fill_quantity > request.order.quantity:
            fill_quantity = request.order.quantity

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
        submitted_at = self._clock.now()
        executed_at = submitted_at + timedelta(milliseconds=self._profile.latency_ms)
        fill = Fill(
            client_order_id=request.order.client_order_id,
            instrument=request.order.instrument,
            side=request.order.side,
            quantity=fill_quantity,
            price=price,
            filled_at=executed_at,
        )
        charges: ChargeBreakdown | None = None
        charge_model = self._profile.charge_model
        if charge_model is None and self._profile.fee_bps != Decimal("0"):
            charge_model = PercentageBpsChargeModel(self._profile.fee_bps)
        if charge_model is not None:
            charges = charge_model.calculate(
                ChargeCalculationContext(
                    transaction_value=fill.quantity * fill.price,
                )
            )
        fee = Decimal("0") if charges is None else charges.total
        slippage_evidence: tuple[str, ...] = ()
        if self._profile.slippage_bps != 0:
            slippage_evidence = (f"reference_price={proposal.price}",)
        receipt = ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=outcome,
            order_status=status,
            executed_at=executed_at,
            fills=(fill,),
            message=proposal.reason,
            simulated=True,
            source="paper",
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            order_quantity=request.order.quantity,
            model_profile=self._profile.name,
            model_version=proposal.model_version,
            assumptions=(
                f"latency_ms={self._profile.latency_ms}",
                f"slippage_bps={self._profile.slippage_bps}",
                *slippage_evidence,
                f"partial_fill_ratio={self._profile.partial_fill_ratio}",
                f"fee_bps={self._profile.fee_bps}",
                *(
                    (
                        f"charge_model_id={charges.model_id}",
                        f"charge_model_version={charges.model_version}",
                        *charges.provenance,
                        f"charge_total={charges.total}",
                    )
                    if charges is not None
                    else ()
                ),
                f"model_id={proposal.model_id}",
                proposal.reason,
            ),
            fee=fee,
            charges=charges,
        )
        if self._receipt_repository is not None:
            self._receipt_repository.save(receipt)
        self._receipts[client_order_id] = receipt
        self._idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
        self._events.append(
            OrderSubmitted(
                event_id=str(uuid4()),
                occurred_at=submitted_at,
                correlation_id=request.correlation_id,
                order_id=str(request.order.client_order_id),
                venue=request.execution_context.market.venue,
            )
        )
        self._events.append(
            OrderFilled(
                event_id=str(uuid4()),
                occurred_at=executed_at,
                correlation_id=request.correlation_id,
                order_id=str(request.order.client_order_id),
                fill_id=str(fill.execution_id),
                quantity=fill.quantity,
                price=fill.price,
            )
        )
        return receipt

    def rebuild_lifecycle(
        self,
        request: ApprovedExecutionRequest,
        lifecycle: ExecutionLifecycle,
    ) -> ExecutionLifecycle:
        """Return the authoritative lifecycle used for continuation decisions."""
        if request.order.client_order_id != lifecycle.client_order_id:
            raise PaperExecutionError("request does not match partial execution lifecycle")
        if self._receipt_repository is None:
            return lifecycle
        receipts = self._receipt_repository.list_by_correlation_id(
            request.order.client_order_id
        )
        if not receipts:
            raise PaperExecutionError(
                "authoritative execution receipts are unavailable; "
                "reconciliation is required"
            )
        try:
            return ExecutionLifecycle.rebuild(
                request.order.client_order_id,
                request.order.quantity,
                receipts,
            )
        except ValueError as exc:
            raise PaperExecutionError(
                f"authoritative execution lifecycle is invalid: {exc}"
            ) from exc

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        lifecycle: ExecutionLifecycle,
        *,
        risk_result: RiskResult,
        snapshot: MarketSnapshot | Candle,
        requested_quantity: Decimal | None = None,
    ) -> ExecutionReceipt:
        """Execute an evidenced partial remainder under fresh risk approval.

        When an authoritative receipt repository is configured, the supplied
        lifecycle is only the caller-side identity check. The continuation
        decision is rebuilt from persisted receipts so a process restart or
        stale in-memory state cannot authorize an unsupported quantity.
        """
        if request.order.client_order_id != lifecycle.client_order_id:
            raise PaperExecutionError("request does not match partial execution lifecycle")

        authoritative_lifecycle = self.rebuild_lifecycle(request, lifecycle)

        try:
            continuation = authoritative_lifecycle.continuation_request(
                request,
                risk_result=risk_result,
                requested_quantity=requested_quantity,
            )
        except ValueError as exc:
            raise PaperExecutionError(str(exc)) from exc
        return self.execute(continuation, snapshot=snapshot)

    def events(self) -> tuple[object, ...]:
        return tuple(self._events)

    def receipt_for(self, client_order_id: UUID) -> ExecutionReceipt | None:
        if self._receipt_repository is not None:
            return self._receipt_repository.get_by_client_order(client_order_id)
        return self._receipts.get(client_order_id)

