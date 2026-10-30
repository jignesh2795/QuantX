"""Dhan plugin models kept outside the QuantX core domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

DhanPayload = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DhanCredentials:
    """Dhan access token plus the broker-supplied expiry instant.

    The token is intentionally excluded from repr. Naive Dhan `expiryTime`
    values are interpreted in Asia/Kolkata as documented by Dhan; all stored
    instants are normalized to UTC.
    """

    client_id: str
    access_token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if type(self.client_id) is not str or not self.client_id.strip():
            raise ValueError("Dhan client_id must not be empty")
        if type(self.access_token) is not str or not self.access_token.strip():
            raise ValueError("Dhan access_token must not be empty")
        if not isinstance(self.expires_at, datetime):
            raise ValueError("Dhan token expires_at must be a datetime")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Dhan token expires_at must be timezone-aware")
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))

    @classmethod
    def from_token_response(
        cls,
        client_id: str,
        response: Mapping[str, Any],
    ) -> DhanCredentials:
        """Build credentials from Dhan's documented access-token response."""
        if not isinstance(response, Mapping):
            raise ValueError("Dhan token response must be a mapping")
        access_token = response.get("accessToken")
        if type(access_token) is not str or not access_token.strip():
            raise ValueError("Dhan token response must contain accessToken")
        returned_client_id = response.get("dhanClientId")
        if returned_client_id is not None and str(returned_client_id).strip() != client_id:
            raise ValueError("Dhan token response client id does not match configured client")
        expiry = _parse_token_expiry(response.get("expiryTime"))
        return cls(client_id=client_id, access_token=access_token, expires_at=expiry)


def _parse_token_expiry(value: object) -> datetime:
    """Parse an ISO expiryTime, assigning Asia/Kolkata only when offset is absent."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Dhan expiryTime must be a valid ISO timestamp") from exc
    else:
        raise ValueError("Dhan token response must contain expiryTime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # IST is fixed at UTC+05:30; avoid requiring an operating-system
        # IANA timezone database (not present by default on Windows).
        india_standard_time = timezone(timedelta(hours=5, minutes=30))
        parsed = parsed.replace(tzinfo=india_standard_time)
    return parsed.astimezone(UTC)


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
class DhanProfileSnapshot:
    """Normalized authenticated profile observation; identity anchor for evidence.

    The profile endpoint is the only Dhan read that independently proves which
    client the authenticated transport belongs to. A missing client id is an
    unavailable observation, never an empty string or a guessed identity.
    """

    observed_at: datetime
    client_id: str | None = None
    available: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.client_id is not None and not self.client_id.strip():
            raise ValueError("client_id must be non-empty when present")


@dataclass(frozen=True, slots=True)
class DhanFundsSnapshot:
    """Normalized broker fund observation; no domain or vendor types."""

    observed_at: datetime
    available_balance: Decimal | None = None
    utilized_amount: Decimal | None = None
    available: bool = True
    message: str = ""
    client_id: str | None = None
    sod_limit: Decimal | None = None
    collateral_amount: Decimal | None = None
    receivable_amount: Decimal | None = None
    blocked_payout_amount: Decimal | None = None
    withdrawable_balance: Decimal | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.client_id is not None and not self.client_id.strip():
            raise ValueError("client_id must be non-empty when present")


@dataclass(frozen=True, slots=True)
class DhanPositionSnapshot:
    """Normalized broker position observation; no domain or vendor types."""

    security_id: str
    exchange_segment: str
    net_quantity: Decimal
    average_price: Decimal | None = None
    client_id: str | None = None
    product_type: str | None = None
    position_type: str | None = None
    buy_quantity: Decimal | None = None
    sell_quantity: Decimal | None = None
    realized_profit: Decimal | None = None
    unrealized_profit: Decimal | None = None
    multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.exchange_segment.strip():
            raise ValueError("exchange_segment must not be empty")
        if self.client_id is not None and not self.client_id.strip():
            raise ValueError("client_id must be non-empty when present")
        if (
            self.buy_quantity is not None
            and self.sell_quantity is not None
            and self.net_quantity != self.buy_quantity - self.sell_quantity
        ):
            raise ValueError("net quantity must equal buy quantity minus sell quantity")
        if self.multiplier is not None and self.multiplier <= 0:
            raise ValueError("multiplier must be positive when present")


@dataclass(frozen=True, slots=True)
class DhanHoldingSnapshot:
    """Normalized delivery-holding observation; no domain or vendor types.

    Holdings rows do not carry a client id. Their identity is bound to the
    authenticated transport by the collection flow, not by a row field.
    """

    security_id: str
    exchange: str
    total_quantity: Decimal
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
        if (
            self.dp_quantity is not None
            and self.t1_quantity is not None
            and self.total_quantity != self.dp_quantity + self.t1_quantity
        ):
            raise ValueError("total quantity must equal dp quantity plus t1 quantity")
        for name in (
            "total_quantity",
            "dp_quantity",
            "t1_quantity",
            "available_quantity",
            "collateral_quantity",
            "average_cost_price",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class DhanHoldingsSnapshot:
    """Normalized broker holdings-book observation; no domain or vendor types."""

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
