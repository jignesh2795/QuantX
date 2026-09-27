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

from quantx.domain.clock import Clock, FixedClock
from uuid import UUID


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

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


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

    def __init__(
        self,
        *,
        accepted: bool = True,
        fill_price: Decimal | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._accepted = accepted
        self._fill_price = fill_price
        self._clock = clock or FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.requests: list[ReferenceOrderRequest] = []

    def health(self) -> bool:
        return True

    def _response(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        self.requests.append(request)
        now = self._clock.now()
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
                f"ref-{request.client_order_id}",
                now,
                message="reference transport accepted the request",
            )
        return ReferenceOrderResponse(
            ReferenceOrderOutcome.FILLED,
            f"ref-{request.client_order_id}",
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
        now = self._clock.now()
        return ReferenceOrderResponse(
            ReferenceOrderOutcome.CANCELLED,
            None,
            now,
            message="reference transport cancelled the request",
        )

    def reconcile(self, request: ReferenceOrderRequest) -> ReferenceOrderResponse:
        return self._response(request)
