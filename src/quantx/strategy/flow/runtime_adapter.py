"""ExecutableStrategy adapter for validated declarative Flow v1 plans."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.strategy import StrategyResult

from ..context import StrategyContext
from .compiler import FlowExecutionPlan
from .interpreter import FlowInterpreter


@dataclass(frozen=True, slots=True)
class FlowExecutableStrategy:
    """Bind one immutable Flow plan to the existing executable-strategy contract.

    The Flow definition and compiled plan remain independent of StrategyIR.
    StrategyRuntime remains responsible for validating the returned result.
    """

    plan: FlowExecutionPlan

    def __post_init__(self) -> None:
        if not isinstance(self.plan, FlowExecutionPlan):
            raise TypeError("plan must be a FlowExecutionPlan")

    def on_market_data(self, context: StrategyContext) -> StrategyResult:
        """Evaluate the bound plan against the exact runtime-created context."""
        return FlowInterpreter().evaluate(self.plan, context)


__all__ = ["FlowExecutableStrategy"]
