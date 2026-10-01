"""Dhan transport boundary.

Only this module may import the third-party DhanHQ SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from .mapping import decimal_field, extract_filled_quantity
from .models import (
    DhanCredentials,
    DhanFundsSnapshot,
    DhanOrderDetail,
    DhanOrderRequest,
    DhanOrderResponse,
    DhanPayload,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
)


@runtime_checkable
class DhanTransport(Protocol):
    def health(self) -> bool: ...

    def submit(self, request: DhanOrderRequest) -> DhanOrderResponse: ...

    def cancel(self, correlation_id: str) -> DhanOrderResponse: ...

    def reconcile(self, correlation_id: str) -> DhanOrderDetail: ...

    def fund_limits(self) -> DhanFundsSnapshot: ...

    def positions(self) -> DhanPositionsSnapshot: ...


class _DhanClient(Protocol):
    def get_fund_limits(self) -> object: ...

    def get_positions(self) -> object: ...

    def place_order(self, **kwargs: object) -> object: ...

    def cancel_order(self, order_id: str) -> object: ...

    def get_order_by_correlationID(self, correlation_id: str) -> object: ...


@dataclass(slots=True)
class DhanSDKTransport:
    """Official DhanHQ SDK wrapper; vendor types never leave this class."""

    credentials: DhanCredentials
    _client: _DhanClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from dhanhq import DhanContext, dhanhq  # type: ignore[import-untyped]

        self._client = dhanhq(
            DhanContext(
                self.credentials.client_id,
                self.credentials.access_token,
            )
        )

    def health(self) -> bool:
        try:
            response = self._client.get_fund_limits()
        except Exception:
            return False
        status, _, _ = _envelope(response)
        return status == "success"

    def submit(self, request: DhanOrderRequest) -> DhanOrderResponse:
        response = self._client.place_order(
            security_id=request.security_id,
            exchange_segment=request.exchange_segment,
            transaction_type=request.transaction_type,
            quantity=request.quantity,
            order_type=request.order_type,
            product_type=request.product_type,
            price=float(request.price),
            trigger_price=float(request.trigger_price),
            validity=request.validity,
            tag=request.correlation_id,
        )
        return _order_response(response)

    def cancel(self, correlation_id: str) -> DhanOrderResponse:
        detail = self.reconcile(correlation_id)
        if detail.order_id is None:
            return DhanOrderResponse(
                order_id=None,
                order_status="UNKNOWN",
                observed_at=datetime.now(UTC),
                message="Dhan order could not be resolved by correlation id",
            )
        response = self._client.cancel_order(detail.order_id)
        return _order_response(response)

    def reconcile(self, correlation_id: str) -> DhanOrderDetail:
        response = self._client.get_order_by_correlationID(correlation_id)
        return _order_detail(response)

    def fund_limits(self) -> DhanFundsSnapshot:
        try:
            response = self._client.get_fund_limits()
        except Exception as exc:
            return DhanFundsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message=f"Dhan fund-limits transport failure: {exc}",
            )
        return _funds_snapshot(response)

    def positions(self) -> DhanPositionsSnapshot:
        try:
            response = self._client.get_positions()
        except Exception as exc:
            return DhanPositionsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message=f"Dhan positions transport failure: {exc}",
            )
        return _positions_snapshot(response)


@dataclass(slots=True)
class InMemoryDhanTransport:
    """Deterministic transport used by QuantX tests; never touches the network."""

    response_status: str = "PENDING"
    order_id: str = "dhan-test-order"
    filled_quantity: Decimal = Decimal("0")
    average_traded_price: Decimal | None = None
    funds_available: bool = True
    funds_available_balance: Decimal | None = Decimal("5000")
    funds_utilized_amount: Decimal | None = Decimal("1200")
    funds_message: str = ""
    positions_available: bool = True
    position_snapshots: tuple[DhanPositionSnapshot, ...] = ()
    positions_message: str = ""
    _submitted: list[DhanOrderRequest] = field(init=False, default_factory=list)
    _cancelled: list[str] = field(init=False, default_factory=list)

    @property
    def submitted(self) -> tuple[DhanOrderRequest, ...]:
        return tuple(self._submitted)

    @property
    def cancelled(self) -> tuple[str, ...]:
        return tuple(self._cancelled)

    def health(self) -> bool:
        return True

    def submit(self, request: DhanOrderRequest) -> DhanOrderResponse:
        self._submitted.append(request)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status=self.response_status,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def cancel(self, correlation_id: str) -> DhanOrderResponse:
        self._cancelled.append(correlation_id)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status="CANCELLED",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def reconcile(self, correlation_id: str) -> DhanOrderDetail:
        return DhanOrderDetail(
            order_id=self.order_id,
            correlation_id=correlation_id,
            order_status=self.response_status,
            average_traded_price=self.average_traded_price,
            filled_quantity=self.filled_quantity,
            exchange_time="2026-01-01 10:00:00",
            update_time="2026-01-01 10:00:00",
        )

    def fund_limits(self) -> DhanFundsSnapshot:
        return DhanFundsSnapshot(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            available_balance=self.funds_available_balance,
            utilized_amount=self.funds_utilized_amount,
            available=self.funds_available,
            message=self.funds_message,
        )

    def positions(self) -> DhanPositionsSnapshot:
        return DhanPositionsSnapshot(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            positions=self.position_snapshots,
            available=self.positions_available,
            message=self.positions_message,
        )


def _order_response(response: object) -> DhanOrderResponse:
    envelope_status, remarks, payload = _envelope(response)
    if envelope_status != "success":
        return DhanOrderResponse(
            order_id=None,
            order_status="UNKNOWN",
            observed_at=datetime.now(UTC),
            message=remarks,
            raw={"status": envelope_status, "remarks": remarks, "data": payload},
        )
    status = str(payload.get("orderStatus", "UNKNOWN"))
    order_id = payload.get("orderId")
    return DhanOrderResponse(
        order_id=str(order_id) if order_id is not None else None,
        order_status=status,
        observed_at=datetime.now(UTC),
        message=str(payload.get("message", "")),
        raw={"status": envelope_status, "remarks": remarks, "data": payload},
    )


def _order_detail(response: object) -> DhanOrderDetail:
    status, remarks, payload = _envelope(response)
    if status != "success":
        return DhanOrderDetail(
            order_id=None,
            correlation_id=None,
            order_status="UNKNOWN",
            average_traded_price=None,
            filled_quantity=Decimal("0"),
            exchange_time=None,
            update_time=None,
            message=remarks,
            raw={"status": status, "remarks": remarks, "data": payload},
        )
    order_id = payload.get("orderId")
    correlation_id = payload.get("correlationId")
    return DhanOrderDetail(
        order_id=str(order_id) if order_id is not None else None,
        correlation_id=(str(correlation_id) if correlation_id is not None else None),
        order_status=str(payload.get("orderStatus", "UNKNOWN")),
        average_traded_price=decimal_field(payload, "averageTradedPrice"),
        filled_quantity=extract_filled_quantity(payload),
        exchange_time=(str(payload["exchangeTime"]) if payload.get("exchangeTime") else None),
        update_time=(str(payload["updateTime"]) if payload.get("updateTime") else None),
        message=str(payload.get("omsErrorDescription", "")),
        raw={"status": status, "remarks": remarks, "data": payload},
    )


def _envelope(response: object) -> tuple[str, str, DhanPayload]:
    if not isinstance(response, dict):
        raise TypeError("Dhan SDK response must be a mapping")
    status = str(response.get("status", "failure"))
    remarks = str(response.get("remarks", ""))
    data = response.get("data")
    if not isinstance(data, dict):
        data = {}
    return status, remarks, data


def _money_field(payload: DhanPayload, key: str) -> Decimal | None:
    """Parse an optional broker money field; missing stays missing, never zero."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Dhan decimal field: {key}") from exc


def _funds_snapshot(response: object) -> DhanFundsSnapshot:
    """Normalize a fund-limits envelope; unusable data stays unavailable."""
    try:
        envelope_status, remarks, payload = _envelope(response)
    except (TypeError, ValueError) as exc:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=f"unrecognized Dhan fund-limits response: {exc}",
        )
    if envelope_status != "success":
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=remarks or "Dhan fund limits reported failure",
        )
    try:
        available_balance = _money_field(payload, "availabelBalance")
        if available_balance is None:
            available_balance = _money_field(payload, "availableBalance")
        utilized_amount = _money_field(payload, "utilizedAmount")
    except ValueError as exc:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=str(exc),
        )
    if available_balance is None and utilized_amount is None:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan fund limits carry no usable balance fields",
        )
    return DhanFundsSnapshot(
        observed_at=datetime.now(UTC),
        available_balance=available_balance,
        utilized_amount=utilized_amount,
        available=True,
        message=remarks,
    )


def _positions_snapshot(response: object) -> DhanPositionsSnapshot:
    """Normalize a positions envelope; malformed data stays unavailable."""
    if not isinstance(response, dict):
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan positions response must be a mapping",
        )
    envelope_status = str(response.get("status", "failure"))
    remarks = str(response.get("remarks", ""))
    if envelope_status != "success":
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=remarks or "Dhan positions reported failure",
        )
    entries = response.get("data")
    if not isinstance(entries, list):
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan positions data must be a list",
        )
    positions: list[DhanPositionSnapshot] = []
    for entry in entries:
        position = _position_snapshot(entry)
        if position is None:
            return DhanPositionsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message="Dhan position entry is malformed",
            )
        positions.append(position)
    return DhanPositionsSnapshot(
        observed_at=datetime.now(UTC),
        positions=tuple(positions),
        available=True,
        message=remarks,
    )


def _position_snapshot(entry: object) -> DhanPositionSnapshot | None:
    if not isinstance(entry, dict):
        return None
    security_id = entry.get("securityId")
    exchange_segment = entry.get("exchangeSegment")
    if security_id is None or not str(security_id).strip():
        return None
    if exchange_segment is None or not str(exchange_segment).strip():
        return None
    try:
        net_quantity = Decimal(str(entry.get("netQty")))
    except (InvalidOperation, ValueError, TypeError):
        return None
    try:
        average_price = _money_field(entry, "costPrice")
    except ValueError:
        return None
    return DhanPositionSnapshot(
        security_id=str(security_id),
        exchange_segment=str(exchange_segment),
        net_quantity=net_quantity,
        average_price=average_price,
    )
