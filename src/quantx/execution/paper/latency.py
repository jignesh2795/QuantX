"""Deterministic latency primitives for simulated execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LatencyModel:
    """Explicit fixed latency; stochastic latency belongs in a future version."""

    order_to_market_ms: int = 0
    market_to_fill_ms: int = 0

    def __post_init__(self) -> None:
        if self.order_to_market_ms < 0 or self.market_to_fill_ms < 0:
            raise ValueError("latency values cannot be negative")

    def fill_time_ns(self, submitted_at_ns: int) -> int:
        if submitted_at_ns < 0:
            raise ValueError("submitted_at_ns cannot be negative")
        total_ms = self.order_to_market_ms + self.market_to_fill_ms
        return submitted_at_ns + total_ms * 1_000_000
