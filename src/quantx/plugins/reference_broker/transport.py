"""Injected transport boundary for the reference broker plugin.

A real vendor SDK wrapper can implement the transport contract without being
imported by QuantX core. The plugin owns translation to and from the
normalized execution contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


class ReferenceOrderOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ReferenceOrderRequest:
    client_order_id: UUID
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    time_in_force: str


@dataclass(frozen=True, slots=True)
class ReferenceOrderFill:
    quantity: Decimal
    price: Decimal
    filled_at: datetime


@dataclass(frozen=True, slots=True)
class ReferenceOrderResponse:
    outcome: ReferenceOrderOutcome
    broker_order_id: str | None
    executed_at: datetime
    fills: tuple[ReferenceOrderFill, ...] = ()
    message: str = ""


class ReferenceBrokerTransport(Protocol):
    """Transport seam where a real vendor SDK wrapper can be injected."""

    def health(self) -> bool:
        ...

    def submit(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        ...

    def cancel(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        ...

    def reconcile(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        ...


class InMemoryReferenceBrokerTransport:
    """Deterministic local transport with no network or external SDK."""

    def __init__(self, *, accepted: bool = True, fill_price: Decimal | None = None) -> None:
        self._accepted = accepted
        self._fill_price = fill_price
        self.requests: list[ReferenceOrderRequest] = []

    def health(self) -> bool:
        return True

    def _response(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        self.requests.append(request)
        now = datetime.now(timezone.utc)
        if not self._accepted:
            return ReferenceOrderResponse(
                ReferenceOrderOutcome.REJECTED,
                None,
                now,
                message="reference transport rejected the request",
            )
        if self._fill_price is None:
            return ReferenceOrderResponse(
                ReferenceOrderOutcome.ACCEPTED,
                f"ref-{uuid4()}",
                now,
                message="reference transport accepted the request",
            )
        return ReferenceOrderResponse(
            ReferenceOrderOutcome.FILLED,
            f"ref-{uuid4()}",
            now,
            fills=(
                ReferenceOrderFill(
                    quantity=request.quantity,
                    price=self._fill_price,
                    filled_at=now,
                ),
            ),
            message="reference transport filled the request",
        )

    def submit(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        return self._response(request)

    def cancel(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        self.requests.append(request)
        now = datetime.now(timezone.utc)
        return ReferenceOrderResponse(
            ReferenceOrderOutcome.CANCELLED,
            None,
            now,
            message="reference transport cancelled the request",
        )

    def reconcile(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        return self._response(request)
