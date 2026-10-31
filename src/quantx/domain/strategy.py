"""Market-neutral strategy identity and signal contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from numbers import Real
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
    """One strategy decision with a bounded, producer-declared score.

    ``confidence`` is a producer-local conviction score normalized to the
    inclusive range ``[0.0, 1.0]``. Accepted ``numbers.Real`` inputs are stored
    canonically as a Python ``float``; ``bool`` is rejected and ``Decimal`` is
    unsupported. It is not a calibrated probability and has no cross-strategy
    or cross-version scale. It is not money, a risk limit, or execution
    authorization; no core consumer selects, sizes, or approves execution from
    it.
    """

    strategy_id: StrategyId
    strategy_version: str
    instrument: InstrumentId
    action: SignalAction
    # Producer-local heuristic score in [0, 1], never a calibrated probability.
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
        confidence = self.confidence
        if isinstance(confidence, bool):
            raise TypeError("signal confidence must not be bool")
        if not isinstance(confidence, Real):
            raise TypeError(
                f"signal confidence must be a numbers.Real, got {type(confidence).__name__}"
            )
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("signal confidence must be between 0.0 and 1.0 inclusive")
        object.__setattr__(self, "confidence", float(confidence))
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
        if not isinstance(self.instrument, InstrumentId):
            raise TypeError("timer instrument must be an InstrumentId")
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
