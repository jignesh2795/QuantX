from dataclasses import dataclass
from decimal import Decimal


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
