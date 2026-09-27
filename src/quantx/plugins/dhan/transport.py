"""Dhan transport boundary.

Only this module may import the third-party DhanHQ SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .models import (
    DhanCredentials,
    DhanOrderDetail,
    DhanOrderRequest,
    DhanOrderResponse,
    DhanPayload,
)
from .mapping import (
    decimal_field,
    extract_filled_quantity,
    parse_dhan_timestamp,
)


class DhanTransport(Protocol):
    def health(self) -> bool:
        ...

    def submit(self, request: DhanOrderRequest) -> DhanOrderResponse:
        ...

    def cancel(self, correlation_id: str) -> DhanOrderResponse:
        ...

    def reconcile(self, correlation_id: str) -> DhanOrderDetail:
        ...


@dataclass(slots=True)
class DhanSDKTransport:
    """Official DhanHQ SDK wrapper; vendor types never leave this class."""

    credentials: DhanCredentials

    def __post_init__(self) -> None:
        from dhanhq import DhanContext, dhanhq

        self._client = dhanhq(
            DhanContext(
                self.credentials.client_id,
                self.credentials.access_token,
            )
        )

    def health(self) -> bool:
        try:
            self._client.get_fund_limits()
        except Exception:
            return False
        return True

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
                observed_at=datetime.now(timezone.utc),
                message="Dhan order could not be resolved by correlation id",
            )
        response = self._client.cancel_order(detail.order_id)
        return _order_response(response)

    def reconcile(self, correlation_id: str) -> DhanOrderDetail:
        response = self._client.get_order_by_correlationID(correlation_id)
        return _order_detail(response)


@dataclass(slots=True)
class InMemoryDhanTransport:
    """Deterministic transport used by QuantX tests; never touches the network."""

    response_status: str = "PENDING"
    order_id: str = "dhan-test-order"
    filled_quantity: Decimal = Decimal("0")
    average_traded_price: Decimal | None = None

    def __post_init__(self) -> None:
        self.submitted: list[DhanOrderRequest] = []
        self.cancelled: list[str] = []

    def health(self) -> bool:
        return True

    def submit(self, request: DhanOrderRequest) -> DhanOrderResponse:
        self.submitted.append(request)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status=self.response_status,
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def cancel(self, correlation_id: str) -> DhanOrderResponse:
        self.cancelled.append(correlation_id)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status="CANCELLED",
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
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


def _order_response(response: object) -> DhanOrderResponse:
    payload = _payload(response)
    status = str(payload.get("orderStatus", "UNKNOWN"))
    order_id = payload.get("orderId")
    return DhanOrderResponse(
        order_id=str(order_id) if order_id is not None else None,
        order_status=status,
        observed_at=datetime.now(timezone.utc),
        message=str(payload.get("message", "")),
        raw=payload,
    )


def _order_detail(response: object) -> DhanOrderDetail:
    payload = _payload(response)
    order_id = payload.get("orderId")
    correlation_id = payload.get("correlationId")
    return DhanOrderDetail(
        order_id=str(order_id) if order_id is not None else None,
        correlation_id=str(correlation_id) if correlation_id is not None else None,
        order_status=str(payload.get("orderStatus", "UNKNOWN")),
        average_traded_price=decimal_field(payload, "averageTradedPrice"),
        filled_quantity=extract_filled_quantity(payload),
        exchange_time=str(payload["exchangeTime"]) if payload.get("exchangeTime") else None,
        update_time=str(payload["updateTime"]) if payload.get("updateTime") else None,
        message=str(payload.get("omsErrorDescription", "")),
        raw=payload,
    )


def _payload(response: object) -> DhanPayload:
    if not isinstance(response, dict):
        raise TypeError("Dhan SDK response must be a mapping")
    return response
