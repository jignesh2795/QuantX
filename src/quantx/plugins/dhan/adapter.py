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
from quantx.integrations.reconciliation.account import (
    AccountFinancialState,
    StateSource,
)
from quantx.integrations.reconciliation.positions import PositionState

from .capabilities import DHAN_CAPABILITIES
from .mapping import (
    build_order_request,
    dhan_correlation_id,
    normalize_status,
    parse_dhan_timestamp,
)
from .models import DhanInstrumentRef, DhanOrderDetail, DhanPositionSnapshot
from .transport import DhanTimeoutError, DhanTransport


@dataclass(slots=True)
class DhanBrokerAdapter:
    """Dhan adapter translating only at the broker-plugin boundary."""

    _connection: BrokerConnectionRef
    _instruments: dict[InstrumentId, tuple[Instrument, DhanInstrumentRef]]
    _transport: DhanTransport
    _submit_timeout: float
    _cancel_timeout: float
    _reconcile_timeout: float
    _capabilities: CapabilitySet = DHAN_CAPABILITIES
    _adapter_version: str = "dhan-0.1"

    def __post_init__(self) -> None:
        if self._connection.broker_id != "dhan":
            raise ValueError("Dhan adapter requires a Dhan broker connection")
        for name, value in (
            ("_submit_timeout", self._submit_timeout),
            ("_cancel_timeout", self._cancel_timeout),
            ("_reconcile_timeout", self._reconcile_timeout),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")

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

    def _validate_connection(self, request: ApprovedExecutionRequest) -> None:
        context = request.execution_context
        if context.account_id != self._connection.account_id:
            raise ValueError("Dhan adapter account does not match execution request account")
        if context.broker_connection_id != self._connection.connection_id:
            raise ValueError("Dhan adapter connection does not match execution request connection")

    def health(self) -> bool:
        return self._transport.health()

    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def instrument(self, instrument_id: InstrumentId) -> Instrument | None:
        item = self._instruments.get(instrument_id)
        return None if item is None else item[0]

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        self._validate_connection(request)
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
            response = self._transport.submit(wire, timeout=self._submit_timeout)
        except DhanTimeoutError as exc:
            return self._unknown_receipt(request, f"Dhan submit timed out after {exc.timeout}s")
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
        self._validate_connection(request)
        try:
            response = self._transport.cancel(
                dhan_correlation_id(request.correlation_id), timeout=self._cancel_timeout
            )
        except DhanTimeoutError as exc:
            return self._unknown_receipt(request, f"Dhan cancel timed out after {exc.timeout}s")
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
        self._validate_connection(request)
        try:
            detail = self._transport.reconcile(
                dhan_correlation_id(request.correlation_id), timeout=self._reconcile_timeout
            )
        except DhanTimeoutError as exc:
            return self._unknown_receipt(request, f"Dhan reconcile timed out after {exc.timeout}s")
        except Exception as exc:
            return self._unknown_receipt(request, f"Dhan reconciliation failure: {exc}")
        if detail.correlation_id is not None:
            expected_correlation = dhan_correlation_id(request.correlation_id)
            if detail.correlation_id != expected_correlation:
                return self._unknown_receipt(
                    request,
                    "Dhan reconciliation returned a mismatched correlation id",
                )
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

    def order_detail(self, *, correlation_id: str) -> DhanOrderDetail:
        """Read-only broker order detail for recovery evidence.

        This performs no submission or cancellation; it only re-observes
        broker state through the transport boundary.
        """
        return self._transport.reconcile(correlation_id, timeout=self._reconcile_timeout)

    def _resolve(
        self,
        instrument_id: InstrumentId,
    ) -> tuple[Instrument, DhanInstrumentRef]:
        try:
            return self._instruments[instrument_id]
        except KeyError as exc:
            raise ValueError(f"Dhan instrument mapping missing: {instrument_id}") from exc

    def account_state(self, *, currency: str = "INR") -> AccountFinancialState:
        """Expose the observed broker balance without inventing missing values."""
        snapshot = self._transport.fund_limits()
        return AccountFinancialState(
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
            observed_at=snapshot.observed_at,
            source=StateSource.BROKER,
            currency=currency,
            available_cash=snapshot.available_balance,
            margin_used=snapshot.utilized_amount,
        )

    def position_states(self) -> tuple[PositionState, ...]:
        """Expose observed broker positions against canonical instruments.

        Unknown instruments and unavailable observations fail closed; nothing
        is inferred or silently dropped.
        """
        snapshot = self._transport.positions()
        if not snapshot.available:
            raise ValueError(f"Dhan position observation unavailable: {snapshot.message}")
        reverse: dict[tuple[str, str], InstrumentId] = {
            (ref.security_id, ref.exchange_segment): instrument_id
            for instrument_id, (_, ref) in self._instruments.items()
        }
        states: list[PositionState] = []
        for position in snapshot.positions:
            instrument_id = reverse.get((position.security_id, position.exchange_segment))
            if instrument_id is None:
                raise ValueError(
                    "Dhan position has no canonical instrument mapping: "
                    f"{position.security_id}/{position.exchange_segment}"
                )
            states.append(
                self._position_state(position, str(instrument_id), snapshot.observed_at)
            )
        return tuple(states)

    def position_state_for(self, instrument_id: str) -> PositionState | None:
        """Return the broker position for one canonical instrument id string.

        Only the requested instrument is evaluated: stray or manual positions
        in other symbols (including symbols with no canonical mapping) are not
        target evidence and never block this lookup. An unavailable position
        book still fails closed, and absence of the target instrument stays
        missing (``None``) rather than inferred as anything else.

        The Dhan positions endpoint reports open positions only; delivered
        (CNC) holdings are not observed here. Absence of a position must
        never be inferred as delivery or settlement. A future read-only
        holdings observation (e.g. ``holding_state_for`` backed by a broker
        holdings endpoint, consumed as corroborating evidence only) is the
        correct boundary for settled-holdings questions.
        """
        snapshot = self._transport.positions()
        if not snapshot.available:
            raise ValueError(f"Dhan position observation unavailable: {snapshot.message}")
        reverse: dict[tuple[str, str], InstrumentId] = {
            (ref.security_id, ref.exchange_segment): instrument_id
            for instrument_id, (_, ref) in self._instruments.items()
        }
        for position in snapshot.positions:
            mapped = reverse.get((position.security_id, position.exchange_segment))
            if mapped is None or str(mapped) != instrument_id:
                continue
            return self._position_state(position, str(mapped), snapshot.observed_at)
        return None

    def _position_state(
        self,
        position: DhanPositionSnapshot,
        instrument_id: str,
        observed_at: datetime,
    ) -> PositionState:
        return PositionState(
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
            instrument_id=instrument_id,
            quantity=position.net_quantity,
            average_price=position.average_price,
            observed_at=observed_at,
            source=StateSource.BROKER,
        )

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
            raise ValueError("Dhan instrument exchange segment does not match request market venue")
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
        if detail.filled_quantity < 0:
            raise ValueError("Dhan reported a negative filled quantity")
        if detail.filled_quantity > request.order.quantity:
            raise ValueError("Dhan filled quantity exceeds canonical order quantity")
        if detail.filled_quantity == 0:
            return ()
        if detail.average_traded_price is None:
            raise ValueError("Dhan filled quantity requires an average traded price")
        filled_at = parse_dhan_timestamp(detail.exchange_time) or parse_dhan_timestamp(
            detail.update_time
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
            executed_at=datetime.now(UTC),
            message=message,
            source="dhan",
            simulated=False,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
        )
