"""Canonical, immutable strategy intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.instruments import MarketContext
from quantx.domain.strategy import StrategyId


@dataclass(frozen=True, slots=True)
class StrategyIR:
    """Normalized strategy definition consumed by executable strategies.

    The IR deliberately contains no broker, runtime, or execution state. It is
    deterministic: equivalent parameter mappings produce identical IR values.
    """

    strategy_id: StrategyId
    version: str
    name: str
    market_contexts: tuple[MarketContext, ...]
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("strategy version must not be empty")
        if not self.name.strip():
            raise ValueError("strategy name must not be empty")
        keys = [key for key, _ in self.parameters]
        if any(not key.strip() for key in keys):
            raise ValueError("strategy parameter names must not be empty")
        if keys != sorted(keys):
            raise ValueError("strategy parameters must be sorted")
        if len(keys) != len(set(keys)):
            raise ValueError("strategy parameter names must be unique")

    def parameter(self, name: str) -> str | None:
        for key, value in self.parameters:
            if key == name:
                return value
        return None
