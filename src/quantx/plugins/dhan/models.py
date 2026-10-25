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
    """Normalized broker position observation; no domain or vendor types.

    The provider response carries significantly more than the net quantity and
    average cost. Those fields are retained so a later completeness decision
    never has to re-read a lossy projection: product/position type, day and
    carry-forward quantities, cost/average prices, multiplier, realized and
    unrealized profit, and derivative metadata are all preserved verbatim as
    parsed values. Missing provider fields stay ``None``; they are never
    defaulted to zero.
    """

    security_id: str
    exchange_segment: str
    net_quantity: Decimal
    average_price: Decimal | None = None
    trading_symbol: str = ""
    product_type: str | None = None
    position_type: str | None = None
    buy_quantity: Decimal | None = None
    sell_quantity: Decimal | None = None
    buy_average_price: Decimal | None = None
    sell_average_price: Decimal | None = None
    realized_profit: Decimal | None = None
    unrealized_profit: Decimal | None = None
    multiplier: Decimal | None = None
    carry_forward_buy_quantity: Decimal | None = None
    carry_forward_sell_quantity: Decimal | None = None
    carry_forward_buy_value: Decimal | None = None
    carry_forward_sell_value: Decimal | None = None
    day_buy_quantity: Decimal | None = None
    day_sell_quantity: Decimal | None = None
    day_buy_value: Decimal | None = None
    day_sell_value: Decimal | None = None
    rbi_reference_rate: Decimal | None = None
    cross_currency: bool | None = None
    drv_expiry_date: str | None = None
    drv_option_type: str | None = None
    drv_strike_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")
        _require_finite_decimal(self.net_quantity, "net_quantity")
        _optional_non_negative(self.average_price, "average_price")
        for name in (
            "buy_quantity",
            "sell_quantity",
            "carry_forward_buy_quantity",
            "carry_forward_sell_quantity",
            "day_buy_quantity",
            "day_sell_quantity",
        ):
            _optional_non_negative(getattr(self, name), name)
        for name in (
            "buy_average_price",
            "sell_average_price",
            "realized_profit",
            "unrealized_profit",
            "carry_forward_buy_value",
            "carry_forward_sell_value",
            "day_buy_value",
            "day_sell_value",
            "rbi_reference_rate",
            "drv_strike_price",
        ):
            _optional_finite_decimal(getattr(self, name), name)
        _optional_positive(self.multiplier, "multiplier")
        if self.cross_currency is not None and type(self.cross_currency) is not bool:
            raise ValueError("cross_currency must be an exact bool when supplied")
        for name in ("trading_symbol", "product_type", "position_type"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise ValueError(f"{name} must be a string when supplied")
        for name in ("drv_expiry_date", "drv_option_type"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise ValueError(f"{name} must be a string when supplied")


@dataclass(frozen=True, slots=True)
class DhanHoldingSnapshot:
    """Normalized broker demat-holding observation; no domain or vendor types.

    ``exchange`` is the provider's holding-level exchange value (the documented
    example is ``ALL``), not an exchange segment. Holding rows carry no
    product type and no observation timestamp, so neither is invented here.
    """

    security_id: str
    exchange: str
    trading_symbol: str = ""
    isin: str | None = None
    total_quantity: Decimal | None = None
    dp_quantity: Decimal | None = None
    t1_quantity: Decimal | None = None
    available_quantity: Decimal | None = None
    collateral_quantity: Decimal | None = None
    average_cost_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange.strip():
            raise ValueError("exchange must not be empty")
        if type(self.trading_symbol) is not str:
            raise ValueError("trading_symbol must be a string")
        if self.isin is not None and type(self.isin) is not str:
            raise ValueError("isin must be a string when supplied")
        for name in (
            "total_quantity",
            "dp_quantity",
            "t1_quantity",
            "available_quantity",
            "collateral_quantity",
            "average_cost_price",
        ):
            _optional_non_negative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class DhanHoldingsSnapshot:
    """Normalized broker holding-book observation; no domain or vendor types."""

    observed_at: datetime
    holdings: tuple[DhanHoldingSnapshot, ...] = ()
    available: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


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


@dataclass(frozen=True, slots=True)
class DhanQuoteSnapshot:
    """Normalized broker quote observation; no domain or vendor types.

    ``observed_at`` is the local read instant. ``trade_observed_at`` is the
    provider's last-trade instant only when the provider value can be
    interpreted unambiguously; it stays ``None`` for a missing, sentinel, or
    unverified-format value. The read instant must never be substituted for a
    provider trade time and then presented as mark freshness.
    """

    security_id: str
    exchange_segment: str
    observed_at: datetime
    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    message: str = ""
    trade_observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.trade_observed_at is not None and (
            self.trade_observed_at.tzinfo is None or self.trade_observed_at.utcoffset() is None
        ):
            raise ValueError("trade_observed_at must be timezone-aware when supplied")
        for name in ("last_price", "bid_price", "ask_price", "bid_size", "ask_size"):
            _optional_non_negative(getattr(self, name), name)


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


def _optional_finite_decimal(value: Decimal | None, name: str) -> None:
    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal when supplied")


def _optional_non_negative(value: Decimal | None, name: str) -> None:
    _optional_finite_decimal(value, name)
    if value is not None and value < 0:
        raise ValueError(f"{name} cannot be negative")


def _optional_positive(value: Decimal | None, name: str) -> None:
    _optional_finite_decimal(value, name)
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be positive when supplied")


def _require_finite_decimal(value: Decimal, name: str) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
