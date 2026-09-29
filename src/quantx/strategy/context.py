"""Runtime-neutral inputs supplied to executable strategies."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.market_data import MarketDataEvent

from .ir import StrategyIR


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Immutable strategy input; contains no execution-mode or broker state."""

    event: MarketDataEvent
    ir: StrategyIR
