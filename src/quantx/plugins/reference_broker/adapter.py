"""Reference broker adapter that contains no vendor SDK dependency."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.domain.value_objects import InstrumentId
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)
from quantx.ports.broker import BrokerPort

from .transport import (
    ReferenceBrokerTransport,
    ReferenceOrderFill,
    ReferenceOrderOutcome,
    ReferenceOrderRequest,
    ReferenceOrderResponse,
)


_OUTCOME_TO_STATUS = {
    ReferenceOrderOutcome.ACCEPTED: (ExecutionOutcome.ACCEPTED, OrderStatus.ACCEPTED),
    ReferenceOrderOutcome.REJECTED: (ExecutionOutcome.REJECTED, OrderStatus.REJECTED),
    ReferenceOrderOutcome.PARTIALLY_FILLED: (
        ExecutionOutcome.PARTIALLY_FILLED,
        OrderStatus.PARTIALLY_FILLED,
    ),
    ReferenceOrderOutcome.FILLED: (ExecutionOutcome.FILLED, OrderStatus.FILLED),
    ReferenceOrderOutcome.CANCELLED: (ExecutionOutcome.CANCELLED, OrderStatus.CANCELLED),
    ReferenceOrderOutcome.UNKNOWN: (ExecutionOutcome.UNKNOWN, OrderStatus.UNKNOWN),
}


@dataclass(slots=True)
class ReferenceBrokerAdapter:
    """Deterministic BrokerPort implementation backed by an injected transport."""

    _connection: BrokerConnectionRef
    _instruments: tuple[Instrument, ...]
    _transport: ReferenceBrokerTransport
    _capabilities: CapabilitySet = CapabilitySet(
        frozenset({
            BrokerCapability.MARKET_DATA,
            BrokerCapability.ORDER_SUBMISSION,
            BrokerCapability.ORDER_CANCELLATION,
            BrokerCapability.PAPER_TRADING,
        })
    )
    _adapter_version: str = "reference-0.1"

    @property
    def descriptor(self) -> BrokerDescriptor:
        return BrokerDescriptor(
            broker_id=self._connection.broker_id,
            display_name="QuantX Reference Broker",
            capabilities=self._capabilities,
            adapter_version=self._adapter_version,
        )

    @property
    def connection(self) -> BrokerConnectionRef:
        return self._connection

    def health(self) -> bool:
        return self._transport.health()

    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def instrument(self, instrument_id: InstrumentId) -> Instrument | None:
        for instrument in self._instruments:
            if instrument.instrument_id == instrument_id:
                return instrument
        return None

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self._execute("submit", request)

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self._execute("cancel", request)

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        return self._execute("reconcile", request)

    def _execute(self, operation: str, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        broker_instrument = self.instrument(request.order.instrument)
        if broker_instrument is None:
            raise ValueError("reference broker does not know the requested instrument")
        if broker_instrument.market != request.execution_context.market:
            raise ValueError("reference broker instrument market does not match request market")

        wire_request = ReferenceOrderRequest(
            client_order_id=request.order.client_order_id,
            symbol=broker_instrument.symbol,
            side=request.order.side.value,
            order_type=request.order.order_type.value,
            quantity=request.order.quantity,
            limit_price=request.order.limit_price,
            stop_price=request.order.stop_price,
            time_in_force=request.order.time_in_force.value,
        )
        if operation == "submit":
            response = self._transport.submit(wire_request)
        elif operation == "cancel":
            response = self._transport.cancel(wire_request)
        else:
            response = self._transport.reconcile(wire_request)
        return self._to_receipt(request, response)

    def _to_receipt(
        self,
        request: ApprovedExecutionRequest,
        response: ReferenceOrderResponse,
    ) -> ExecutionReceipt:
        outcome, order_status = _OUTCOME_TO_STATUS[response.outcome]
        fills = tuple(self._to_fill(request, fill) for fill in response.fills)
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=outcome,
            order_status=order_status,
            executed_at=response.executed_at,
            fills=fills,
            message=response.message,
            simulated=True,
            source="reference-broker",
            broker_order_id=response.broker_order_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )

    @staticmethod
    def _to_fill(
        request: ApprovedExecutionRequest,
        fill: ReferenceOrderFill,
    ):
        from quantx.domain.orders import Fill

        return Fill(
            client_order_id=request.order.client_order_id,
            instrument=request.order.instrument,
            side=request.order.side,
            quantity=fill.quantity,
            price=fill.price,
            filled_at=fill.filled_at,
        )


def assert_broker_port(adapter: ReferenceBrokerAdapter) -> BrokerPort:
    """Return a statically documented adapter as the canonical broker port."""
    return adapter
