"""Market-neutral strategy identity and signal contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
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
    # Wall-clock default for interactive construction only. Replay callers
    # must bind the market-event time explicitly: the deterministic backtest
    # rejects any signal whose timestamp differs from the replay frame.
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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
class TimerRequest:
    """One-shot, instrument-scoped timer requested by a validated strategy result."""

    timer_id: str
    instrument: InstrumentId
    due_at: datetime

    def __post_init__(self) -> None:
        if not self.timer_id.strip():
            raise ValueError("timer_id must not be empty")
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValueError("timer due_at must be timezone-aware")
        object.__setattr__(self, "due_at", self.due_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class StrategyResult:
    signal: StrategySignal
    intent: TradeIntent | None = None
    timers: tuple[TimerRequest, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.timers, tuple):
            raise TypeError("strategy result timers must be an immutable tuple")
        if any(not isinstance(timer, TimerRequest) for timer in self.timers):
            raise TypeError("strategy result timers must contain TimerRequest values")
