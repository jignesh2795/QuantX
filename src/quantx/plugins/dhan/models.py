"""Dhan plugin models kept outside the QuantX core domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

DhanPayload = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DhanCredentials:
    client_id: str
    access_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("Dhan client_id must not be empty")
        if not self.access_token.strip():
            raise ValueError("Dhan access_token must not be empty")


@dataclass(frozen=True, slots=True)
class DhanInstrumentRef:
    """Broker-specific instrument mapping for one canonical QuantX instrument."""

    security_id: str
    exchange_segment: str
    trading_symbol: str
    product_type: str

    def __post_init__(self) -> None:
        for name, value in (
            ("security_id", self.security_id),
            ("exchange_segment", self.exchange_segment),
            ("trading_symbol", self.trading_symbol),
            ("product_type", self.product_type),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class DhanOrderRequest:
    security_id: str
    exchange_segment: str
    transaction_type: str
    quantity: int
    order_type: str
    product_type: str
    price: Decimal
    trigger_price: Decimal
    validity: str
    correlation_id: str

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Dhan quantity must be positive")
        if len(self.correlation_id) > 30:
            raise ValueError("Dhan correlation_id must not exceed 30 characters")
        if not self.correlation_id.strip():
            raise ValueError("Dhan correlation_id must not be empty")


@dataclass(frozen=True, slots=True)
class DhanOrderResponse:
    order_id: str | None
    order_status: str
    observed_at: datetime
    message: str = ""
    raw: DhanPayload | None = None


@dataclass(frozen=True, slots=True)
class DhanOrderDetail:
    order_id: str | None
    correlation_id: str | None
    order_status: str
    average_traded_price: Decimal | None
    filled_quantity: Decimal
    exchange_time: str | None
    update_time: str | None
    message: str = ""
    raw: DhanPayload | None = None


@dataclass(frozen=True, slots=True)
class DhanFundsSnapshot:
    """Normalized broker fund observation; no domain or vendor types."""

    observed_at: datetime
    available_balance: Decimal | None = None
    utilized_amount: Decimal | None = None
    available: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DhanPositionSnapshot:
    """Normalized broker position observation; no domain or vendor types."""

    security_id: str
    exchange_segment: str
    net_quantity: Decimal
    average_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")


@dataclass(frozen=True, slots=True)
class DhanPositionsSnapshot:
    """Normalized broker position-book observation; no domain or vendor types."""

    observed_at: datetime
    positions: tuple[DhanPositionSnapshot, ...] = ()
    available: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
