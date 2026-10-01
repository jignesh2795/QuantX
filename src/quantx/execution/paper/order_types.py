"""Order-type primitives for the paper execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PaperOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass(frozen=True, slots=True)
class PaperOrderSpec:
    side: str
    order_type: PaperOrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type in {PaperOrderType.LIMIT, PaperOrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit_price is required")
        if self.order_type in {PaperOrderType.STOP, PaperOrderType.STOP_LIMIT} and self.stop_price is None:
            raise ValueError("stop_price is required")
