from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


def canonical_decimal(value: Decimal) -> str:
    """Render a Decimal independent of its trailing-zero scale.

    Serialized identity must not change when a source catalog spells the same
    value as ``25000`` or ``25000.00``: execution semantics are the numeric
    value, not the textual precision that happened to carry it.
    """
    if not value.is_finite():
        return str(value)
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def canonical_instant(value: datetime) -> str:
    """Render one instant deterministically regardless of its UTC offset.

    The same instant observed as ``+05:30`` or ``Z`` is one execution
    semantic. Fixed microsecond precision keeps serialization round-trips
    stable without truncating the value.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical instants must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.currency:
            raise ValueError("currency must not be empty")

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(Decimal("0"), currency)


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("quantity cannot be negative")


@dataclass(frozen=True, slots=True)
class InstrumentId:
    venue: str
    symbol: str

    def __post_init__(self) -> None:
        if not self.venue or not self.symbol:
            raise ValueError("venue and symbol are required")

    def __str__(self) -> str:
        return f"{self.venue}:{self.symbol}"

    def to_payload(self) -> dict[str, str]:
        """Canonical serializable identity, never a symbol-derived string."""
        return {"venue": self.venue, "symbol": self.symbol}

    @classmethod
    def from_payload(cls, payload: object) -> "InstrumentId":
        """Rebuild a stable instrument identity, rejecting anything unexpected."""
        if not isinstance(payload, dict):
            raise ValueError("instrument id must be an object")
        if set(payload) != {"venue", "symbol"}:
            raise ValueError("instrument id has unexpected fields")
        venue = payload["venue"]
        symbol = payload["symbol"]
        if not isinstance(venue, str) or not isinstance(symbol, str):
            raise ValueError("instrument id venue and symbol must be strings")
        return cls(venue=venue, symbol=symbol)


@dataclass(frozen=True, slots=True)
class AccountId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("account id must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProductCode:
    """Opaque, market-pack-scoped product identity (not an instrument property)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("product code must not be empty or whitespace")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BrokerConnectionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("broker connection id must not be empty")

    def __str__(self) -> str:
        return self.value
