"""Normalized Dhan BrokerPort implementation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from quantx.domain.accounts import Account
from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import DERIVATIVE_ASSET_CLASSES, Instrument
from quantx.domain.risk_evidence import (
    RealizedDailyPnlEvidence,
    WholeAccountPositionEvidence,
)
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts.models import (
    ExecutionEvidenceKind,
    ExecutionOutcome,
    ExecutionReceipt,
)
from quantx.execution.submission_preflight import BrokerPreflightRejected
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
from .daily_pnl import DhanRealizedDailyPnlSource
from .financial_authority import (
    DhanFinancialAuthorityAssessment,
    DhanFinancialAuthoritySource,
)
from .mapping import (
    build_order_request,
    dhan_correlation_id,
    dhan_product_type,
    normalize_dhan_product_map,
    normalize_status,
    parse_dhan_timestamp,
)
from .models import DhanInstrumentRef, DhanOrderDetail, DhanPositionSnapshot
from .position_evidence import DhanWholeAccountPositionSource
from .transport import DEFAULT_READ_TIMEOUT_SECONDS, DhanTimeoutError, DhanTransport


@dataclass(slots=True)
class DhanBrokerAdapter:
    """Dhan adapter translating only at the broker-plugin boundary."""

    _connection: BrokerConnectionRef
    _instruments: dict[InstrumentId, tuple[Instrument, DhanInstrumentRef]]
    _transport: DhanTransport
    _submit_timeout: float
    _cancel_timeout: float
    _reconcile_timeout: float
    _read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    _capabilities: CapabilitySet = DHAN_CAPABILITIES
    _adapter_version: str = "dhan-0.1"
    _product_map: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self._connection.broker_id != "dhan":
            raise ValueError("Dhan adapter requires a Dhan broker connection")
        for name, value in (
            ("_submit_timeout", self._submit_timeout),
            ("_cancel_timeout", self._cancel_timeout),
            ("_reconcile_timeout", self._reconcile_timeout),
            ("_read_timeout", self._read_timeout),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive number")
        if self._product_map is not None:
            object.__setattr__(self, "_product_map", normalize_dhan_product_map(self._product_map))

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

    def _validate_product(self, request: ApprovedExecutionRequest) -> None:
        try:
            dhan_product_type(request.product, product_map=self._product_map)
        except ValueError as exc:
            if request.product is None:
                raise BrokerPreflightRejected(
                    "Dhan submission requires an approved resolved product; "
                    "instrument references carry no product default"
                ) from exc
            raise BrokerPreflightRejected(
                f"unsupported product for Dhan adapter: {request.product.value}"
            ) from exc

    def _validate_contract(
        self,
        request: ApprovedExecutionRequest,
        instrument: Instrument,
    ) -> None:
        """Require canonical contract metadata for a derivative submission.

        Contract facts come only from the canonical point-in-time resolution;
        the adapter never parses expiry, strike, underlying, or option type
        from a trading symbol or vendor reference. A derivative request whose
        resolution is missing or contradicts the mapped canonical instrument
        is rejected locally, before transport.
        """
        resolution = request.instrument_resolution
        if resolution is not None and resolution.instrument != instrument:
            raise BrokerPreflightRejected(
                "resolved instrument contradicts the mapped Dhan instrument"
            )
        if instrument.asset_class in DERIVATIVE_ASSET_CLASSES:
            if resolution is None or resolution.contract is None:
                raise BrokerPreflightRejected(
                    "Dhan submission requires resolved derivative contract metadata"
                )
            contract = resolution.contract
            if contract.instrument_id != instrument.instrument_id:
                raise BrokerPreflightRejected(
                    "resolved contract metadata does not match the mapped Dhan instrument"
                )
            if contract.asset_class is not instrument.asset_class:
                raise BrokerPreflightRejected(
                    "resolved contract asset class does not match the mapped Dhan instrument"
                )
            return
        if resolution is not None and resolution.contract is not None:
            raise BrokerPreflightRejected(
                "a non-derivative Dhan submission cannot carry contract metadata"
            )

    def health(self) -> bool:
        return self._transport.health(timeout=self._read_timeout)

    def capabilities(self) -> CapabilitySet:
        return self._capabilities

    def instrument(self, instrument_id: InstrumentId) -> Instrument | None:
        item = self._instruments.get(instrument_id)
        return None if item is None else item[0]

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        # Preflight boundary: connection, instrument, market, and wire-request
        # validation all run before any transport I/O. A failure here is a
        # deterministic local rejection proven not to have reached the broker,
        # so it is surfaced through the typed NOT_SUBMITTED contract instead of
        # an ambiguous post-submission exception.
        try:
            self._validate_connection(request)
            broker_instrument = self._resolve(request.order.instrument)
            self._validate_contract(request, broker_instrument[0])
            self._validate_market(broker_instrument[0], broker_instrument[1])
            self._validate_product(request)
            wire = build_order_request(
                instrument_ref=broker_instrument[1],
                side=request.order.side,
                order_type=request.order.order_type,
                quantity=request.order.quantity,
                limit_price=request.order.limit_price,
                stop_price=request.order.stop_price,
                time_in_force=request.order.time_in_force,
                correlation_id=request.correlation_id,
                product_code=request.product,
                product_map=self._product_map,
            )
        except BrokerPreflightRejected:
            raise
        except Exception as exc:
            raise BrokerPreflightRejected(
                f"Dhan preflight validation failed before transport submission: {exc}"
            ) from exc
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
            order_quantity=request.order.quantity,
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
            order_quantity=request.order.quantity,
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
        # The Dhan order detail is the only broker response that echoes the
        # correlation id. A success observation without the echo cannot be
        # bound to the requested order, so missing echo evidence must not
        # silently become a definitive receipt; it stays UNKNOWN and the
        # pending reservation remains with reconciliation.
        if detail.correlation_id is None:
            return self._unknown_receipt(
                request,
                "Dhan reconciliation response did not confirm the correlation id",
            )
        expected_correlation = dhan_correlation_id(request.correlation_id)
        if detail.correlation_id != expected_correlation:
            return self._unknown_receipt(
                request,
                "Dhan reconciliation returned a mismatched correlation id",
            )
        outcome_value, status = normalize_status(detail.order_status)
        executed_at = (
            parse_dhan_timestamp(detail.exchange_time)
            or parse_dhan_timestamp(detail.update_time)
            or datetime.now(UTC)
        )
        # Dhan reconcile reports filled_quantity as a cumulative observation
        # of total filled so far, not as a delta. Produce a
        # CUMULATIVE_OBSERVATION receipt when a positive quantity is reported.
        if detail.filled_quantity > 0:
            if detail.filled_quantity > request.order.quantity:
                raise ValueError("Dhan filled quantity exceeds canonical order quantity")
            # A positive observed fill still requires a price observation. The
            # cumulative average traded price is retained as separately
            # identified observation metadata, never as an independently
            # evidenced execution price or a synthetic Fill.
            if detail.average_traded_price is None:
                raise ValueError("Dhan filled quantity requires an average traded price")
            return ExecutionReceipt(
                request_id=uuid4(),
                client_order_id=request.order.client_order_id,
                outcome=ExecutionOutcome(outcome_value),
                order_status=status,
                executed_at=executed_at,
                fills=(),
                message=detail.message,
                source="dhan",
                simulated=False,
                broker_order_id=detail.order_id,
                correlation_id=request.correlation_id,
                order_id=request.order.client_order_id,
                order_quantity=request.order.quantity,
                account_id=request.execution_context.account_id,
                connection_id=request.execution_context.broker_connection_id,
                evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
                observed_filled_quantity=detail.filled_quantity,
                observed_average_price=detail.average_traded_price,
            )
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome(outcome_value),
            order_status=status,
            executed_at=executed_at,
            fills=(),
            message=detail.message,
            source="dhan",
            simulated=False,
            broker_order_id=detail.order_id,
            correlation_id=request.correlation_id,
            order_id=request.order.client_order_id,
            order_quantity=request.order.quantity,
            account_id=request.execution_context.account_id,
            connection_id=request.execution_context.broker_connection_id,
            evidence_kind=ExecutionEvidenceKind.CUMULATIVE_OBSERVATION,
            observed_filled_quantity=detail.filled_quantity,
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
        snapshot = self._transport.fund_limits(timeout=self._read_timeout)
        return AccountFinancialState(
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
            observed_at=snapshot.observed_at,
            source=StateSource.BROKER,
            currency=currency,
            available_cash=snapshot.available_balance,
            margin_used=snapshot.utilized_amount,
        )

    def realized_daily_pnl_evidence(
        self,
        *,
        trading_day: date,
        day_start_at: datetime,
        as_of: datetime,
    ) -> RealizedDailyPnlEvidence:
        """Return explicit unavailable C2a evidence bound to this connection.

        Dhan's verified provider contracts cannot prove complete whole-account
        realized daily P&L, so this method never returns ``COMPLETE`` and
        performs no broker I/O. The C1 evidence builder rejects the result
        before risk evaluation or submission.
        """
        return DhanRealizedDailyPnlSource(
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
            broker_id=self._connection.broker_id,
        ).observe_realized_daily_pnl(
            trading_day=trading_day,
            day_start_at=day_start_at,
            as_of=as_of,
        )

    def financial_authority_assessment(
        self,
        *,
        account: Account,
        assessed_at: datetime,
    ) -> DhanFinancialAuthorityAssessment:
        """Return explicit C2c financial-authority blockers for this account.

        The caller must load the account from the durable account repository.
        Dhan fund-limit and margin-calculator contracts cannot construct the
        complete C1 financial state, so this emits no monetary evidence and
        performs no broker I/O.
        """
        return DhanFinancialAuthoritySource(
            account=account,
            connection=self._connection,
        ).assess(assessed_at=assessed_at)

    def whole_account_position_evidence(
        self,
        *,
        observed_at: datetime,
    ) -> WholeAccountPositionEvidence:
        """Observe Dhan portfolio surfaces and return explicit C2b refusal.

        Dhan does not establish holdings product/quantity/overlap semantics, a
        provider book timestamp, or an authorized mark timestamp. The source
        therefore never returns ``COMPLETE`` and emits no unmarked canonical
        positions. It reads only the two portfolio surfaces through the
        existing transport boundary; it does not query market quotes.
        """
        return DhanWholeAccountPositionSource(
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
            instruments=self._instruments,
            transport=self._transport,
            product_map=self._product_map,
            read_timeout=self._read_timeout,
        ).observe_whole_account_positions(observed_at=observed_at)

    def position_states(self) -> tuple[PositionState, ...]:
        """Expose observed broker positions against canonical instruments.

        Unknown instruments and unavailable observations fail closed; nothing
        is inferred or silently dropped.
        """
        snapshot = self._transport.positions(timeout=self._read_timeout)
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
            states.append(self._position_state(position, str(instrument_id), snapshot.observed_at))
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
        snapshot = self._transport.positions(timeout=self._read_timeout)
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
