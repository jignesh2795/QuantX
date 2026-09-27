"""Market-neutral strategy contracts.

Strategies produce observations/signals and trade intents. They do not submit
broker-specific orders and do not receive broker credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from .instruments import MarketContext
from .order_intents import TradeIntent
from .value_objects import InstrumentId


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class StrategyId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("strategy id must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: StrategyId
    version: str
    name: str
    market_contexts: tuple[MarketContext, ...] = ()
    parameters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("strategy version must not be empty")
        if not self.name.strip():
            raise ValueError("strategy name must not be empty")


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy_id: StrategyId
    strategy_version: str
    instrument: InstrumentId
    action: SignalAction
    confidence: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""
    signal_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.strategy_version.strip():
            raise ValueError("strategy version must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("signal confidence must be between 0 and 1")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class StrategyResult:
    signal: StrategySignal
    intent: TradeIntent | None = None
