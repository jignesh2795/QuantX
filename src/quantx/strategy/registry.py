"""In-memory registry for executable strategy implementations."""

from __future__ import annotations

from collections.abc import Callable

from .ir import StrategyIR
from .runtime import ExecutableStrategy


StrategyFactory = Callable[[], ExecutableStrategy]


class StrategyRegistry:
    """Resolve immutable IR identities to fresh executable strategy instances."""

    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], StrategyFactory] = {}

    def register(self, strategy_id: str, version: str, factory: StrategyFactory) -> None:
        key = self._key(strategy_id, version)
        if key in self._factories:
            raise ValueError(f"strategy already registered: {strategy_id}@{version}")
        self._factories[key] = factory

    def resolve(self, ir: StrategyIR) -> ExecutableStrategy:
        try:
            factory = self._factories[(ir.strategy_id.value, ir.version)]
        except KeyError as exc:
            raise KeyError(
                f"strategy is not registered: {ir.strategy_id.value}@{ir.version}"
            ) from exc
        return factory()

    def _key(self, strategy_id: str, version: str) -> tuple[str, str]:
        if not strategy_id.strip() or not version.strip():
            raise ValueError("strategy id and version are required")
        return strategy_id, version
