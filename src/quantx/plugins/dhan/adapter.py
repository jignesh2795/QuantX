"""Normalized Dhan BrokerPort implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts.models import ExecutionOutcome, ExecutionReceipt
from quantx.integrations.brokers import (
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)
from quantx.ports.broker import BrokerPort

from .capabilities import DHAN_CAPABILITIES
from .mapping import (
    build_order_request,
    dhan_correlation_id,
    normalize_status,
    parse_dhan_timestamp,
)
from .models import DhanInstrumentRef, DhanOrderDetail
from .transport import DhanTransport


@dataclass(slots=True)
class DhanBrokerAdapter:
    """Dhan adapter translating only at the broker-plugin boundary."""

    _connection: BrokerConnectionRef
    _instruments: dict[InstrumentId, tuple[Instrument, DhanInstrumentRef]]
    _transport: DhanTransport
    _capabilities: CapabilitySet = DHAN_CAPABILITIES
    _adapter_version: str = "dhan-0.1"

    def __post_init__(self) -> None:
        if self._connection.broker_id != "dhan":
            raise ValueError("Dhan adapter requires a Dhan broker connection")

    @property
    def descriptor(self) -> BrokerDescriptor:
        return BrokerDescriptor(
            broker_id="dhan",
            display_name="Dhan",
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
        item = self._instruments.get(instrument_id)
        return None if item is None else item[0]

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        broker_instrument = self._resolve(request.order.instrument)
        self._validate_market(broker_instrument[0], broker_instrument[1])
        wire = build_order_request(
            instrument_ref=broker_instrument[1],
            side=request.order.side,
            order_type=request.order.order_type,
            quantity=request.order.quantity,
            limit_price=request.order.limit_price,
            stop_price=request.order.stop_price,
            time_in_force=request.order.time_in_force,
            correlation_id=request.correlation_id,
        )
        try:
            response = self._transport.submit(wire)
        except Exception as exc:
            return self._unknown_receipt(request, f"Dhan transport failure: {exc}")
        outcome, status = normalize_status(response.order_status)
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome(outcome),
            order_status=status,
            executed_at=response.observed_at,
            message=response.message,
            source="dhan",
            simulated=False,
            broker_order_id=response.order_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        try:
            response = self._transport.cancel(dhan_correlation_id(request.correlation_id))
        except Exception as exc:
            return self._unknown_receipt(request, f"Dhan cancel transport failure: {exc}")
        outcome, status = normalize_status(response.order_status)
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome(outcome),
            order_status=status,
            executed_at=response.observed_at,
            message=response.message,
            source="dhan",
            simulated=False,
            broker_order_id=response.order_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        try:
            detail = self._transport.reconcile(dhan_correlation_id(request.correlation_id))
        except Exception as exc:
            return self._unknown_receipt(request, f"Dhan reconciliation failure: {exc}")
        outcome_value, status = normalize_status(detail.order_status)
        fills = self._fill_from_detail(request, detail)
        executed_at = (
            parse_dhan_timestamp(detail.exchange_time)
            or parse_dhan_timestamp(detail.update_time)
            or datetime.now(UTC)
        )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome(outcome_value),
            order_status=status,
            executed_at=executed_at,
            fills=fills,
            message=detail.message,
            source="dhan",
            simulated=False,
            broker_order_id=detail.order_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )

    def _resolve(
        self,
        instrument_id: InstrumentId,
    ) -> tuple[Instrument, DhanInstrumentRef]:
        try:
            return self._instruments[instrument_id]
        except KeyError as exc:
            raise ValueError(f"Dhan instrument mapping missing: {instrument_id}") from exc

    @staticmethod
    def _validate_market(
        instrument: Instrument,
        instrument_ref: DhanInstrumentRef,
    ) -> None:
        segment_venue = {
            "NSE_EQ": "NSE",
            "NSE_FNO": "NSE",
            "BSE_EQ": "BSE",
            "BSE_FNO": "BSE",
            "MCX_COMM": "MCX",
        }.get(instrument_ref.exchange_segment)
        if segment_venue is None:
            raise ValueError(
                f"unsupported Dhan exchange segment: {instrument_ref.exchange_segment}"
            )
        if instrument.market.venue.upper() != segment_venue:
            raise ValueError(
                "Dhan instrument exchange segment does not match request market venue"
            )
        if instrument_ref.product_type.upper() not in {
            "CNC",
            "INTRADAY",
            "MARGIN",
            "MTF",
        }:
            raise ValueError(
                f"unsupported Dhan regular-order product type: {instrument_ref.product_type}"
            )

    @staticmethod
    def _fill_from_detail(
        request: ApprovedExecutionRequest,
        detail: DhanOrderDetail,
    ) -> tuple[Fill, ...]:
        if detail.filled_quantity <= 0 or detail.average_traded_price is None:
            return ()
        filled_at = (
            parse_dhan_timestamp(detail.exchange_time)
            or parse_dhan_timestamp(detail.update_time)
        )
        if filled_at is None:
            return ()
        return (
            Fill(
                client_order_id=request.order.client_order_id,
                instrument=request.order.instrument,
                side=request.order.side,
                quantity=detail.filled_quantity,
                price=detail.average_traded_price,
                filled_at=filled_at,
            ),
        )

    @staticmethod
    def _unknown_receipt(
        request: ApprovedExecutionRequest,
        message: str,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.UNKNOWN,
            order_status=OrderStatus.UNKNOWN,
            executed_at=datetime.now(timezone.utc),
            message=message,
            source="dhan",
            simulated=False,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )
