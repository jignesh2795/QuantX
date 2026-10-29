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
    """Broker-specific instrument mapping for one canonical QuantX instrument.

    Instrument identity carries no per-order product. The approved request
    product is the sole authority and is mapped by ``mapping.dhan_product_type``.
    """

    security_id: str
    exchange_segment: str
    trading_symbol: str

    def __post_init__(self) -> None:
        for name, value in (
            ("security_id", self.security_id),
            ("exchange_segment", self.exchange_segment),
            ("trading_symbol", self.trading_symbol),
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
    """Normalized broker fund observation; no domain or vendor types.

    dhan_client_id is copied from the authenticated fund-limit response,
    never inferred from the host's configured account identity.
    """

    observed_at: datetime
    available_balance: Decimal | None = None
    utilized_amount: Decimal | None = None
    available: bool = True
    message: str = ""
    dhan_client_id: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.dhan_client_id is not None and (
            type(self.dhan_client_id) is not str or not self.dhan_client_id.strip()
        ):
            raise ValueError("dhan_client_id must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class DhanPositionSnapshot:
    """Normalized broker position observation; no domain or vendor types."""

    security_id: str
    exchange_segment: str
    net_quantity: Decimal
    average_price: Decimal | None = None
    realized_profit: Decimal | None = None
    unrealized_profit: Decimal | None = None
    dhan_client_id: str | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")
        if self.dhan_client_id is not None and (
            type(self.dhan_client_id) is not str or not self.dhan_client_id.strip()
        ):
            raise ValueError("dhan_client_id must be a non-empty string or None")
        for name in ("net_quantity", "average_price", "realized_profit", "unrealized_profit"):
            value = getattr(self, name)
            if value is not None and (type(value) is not Decimal or not value.is_finite()):
                raise ValueError(f"{name} must be a finite Decimal or None")


@dataclass(frozen=True, slots=True)
class DhanPositionsSnapshot:
    """Normalized broker position-book observation; no domain or vendor types."""

    observed_at: datetime
    positions: tuple[DhanPositionSnapshot, ...] = ()
    available: bool = True
    message: str = ""
    dhan_client_id: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.dhan_client_id is not None and (
            type(self.dhan_client_id) is not str or not self.dhan_client_id.strip()
        ):
            raise ValueError("dhan_client_id must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class DhanHoldingSnapshot:
    """One normalized demat holding; distinct from an open trading position."""

    security_id: str
    exchange: str
    trading_symbol: str
    isin: str
    total_quantity: Decimal
    delivered_quantity: Decimal
    pending_delivery_quantity: Decimal
    available_quantity: Decimal
    collateral_quantity: Decimal
    average_cost_price: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("security_id", "exchange", "trading_symbol", "isin"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in (
            "total_quantity",
            "delivered_quantity",
            "pending_delivery_quantity",
            "available_quantity",
            "collateral_quantity",
        ):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite non-negative Decimal")
        if self.average_cost_price is not None and (
            type(self.average_cost_price) is not Decimal
            or not self.average_cost_price.is_finite()
            or self.average_cost_price < 0
        ):
            raise ValueError("average_cost_price must be a finite non-negative Decimal or None")


@dataclass(frozen=True, slots=True)
class DhanHoldingsSnapshot:
    """One normalized holdings response or an explicit unavailable state.

    The API response has no per-row client identity. Consumers must bind this
    observation to the same authenticated transport and a separately verified
    fund-limit client ID before using it as account-specific evidence.
    """

    observed_at: datetime
    holdings: tuple[DhanHoldingSnapshot, ...] = ()
    available: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DhanQuoteSnapshot:
    """Normalized broker quote observation; no domain or vendor types."""

    security_id: str
    exchange_segment: str
    observed_at: datetime
    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for name in ("last_price", "bid_price", "ask_price", "bid_size", "ask_size"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class DhanCandleSnapshot:
    """Normalized broker candle observation; no domain or vendor types."""

    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.timeframe.strip():
            raise ValueError("timeframe must not be empty")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
