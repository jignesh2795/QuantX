"""Runtime-neutral, immutable inputs supplied to executable strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from quantx.domain.market_data import Candle, MarketDataEvent

from .engine_snapshot import EngineStateSnapshot, unavailable_engine_snapshot
from .ir import StrategyIR
from .typed_params import TypedParams


@dataclass(frozen=True, slots=True, init=False)
class StrategyContext:
    """One read-only information cut; contains no broker or execution capability."""

    event: MarketDataEvent | None
    ir: StrategyIR
    as_of: datetime
    engine: EngineStateSnapshot
    history: tuple[Candle, ...]
    params: TypedParams

    def __init__(
        self,
        event: MarketDataEvent | None,
        ir: StrategyIR,
        *,
        as_of: datetime | None = None,
        engine: EngineStateSnapshot | None = None,
        history: tuple[Candle, ...] = (),
    ) -> None:
        if as_of is None:
            if event is None:
                raise ValueError("as_of is required when event is None")
            as_of = event.timestamp
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        logical_time = as_of.astimezone(UTC)
        snapshot = engine or unavailable_engine_snapshot(
            logical_time,
            "engine snapshot was not supplied by an authoritative driver",
        )
        if snapshot.as_of != logical_time:
            raise ValueError("engine snapshot as_of must equal context as_of")
        if not isinstance(history, tuple):
            raise TypeError("history must be an immutable tuple")
        for candle in history:
            if not isinstance(candle, Candle):
                raise TypeError("history may contain only canonical Candle objects")
            if candle.timestamp.astimezone(UTC) >= logical_time:
                raise ValueError("history candles must be strictly prior to as_of")
            if event is not None and candle.instrument != event.instrument:
                raise ValueError("history candles must match the event instrument")
        object.__setattr__(self, "event", event)
        object.__setattr__(self, "ir", ir)
        object.__setattr__(self, "as_of", logical_time)
        object.__setattr__(self, "engine", snapshot)
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "params", TypedParams.from_ir(ir))
