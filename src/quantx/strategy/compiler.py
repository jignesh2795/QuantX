"""Compilation from domain strategy definitions to canonical IR."""

from __future__ import annotations

from quantx.domain.strategy import StrategyDefinition

from .ir import StrategyIR


class StrategyCompiler:
    """Compile domain definitions without introducing runtime side effects."""

    @staticmethod
    def compile(definition: StrategyDefinition) -> StrategyIR:
        parameters = tuple(sorted((key, value) for key, value in definition.parameters.items()))
        return StrategyIR(
            strategy_id=definition.strategy_id,
            version=definition.version,
            name=definition.name,
            market_contexts=definition.market_contexts,
            parameters=parameters,
        )
