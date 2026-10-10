import pytest

from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry


class StubStrategy:
    def on_market_data(self, event, ir):
        raise NotImplementedError


def test_registry_resolves_fresh_instances() -> None:
    registry = StrategyRegistry()
    registry.register("stub", "1", StubStrategy)
    ir = StrategyCompiler.compile(StrategyDefinition(StrategyId("stub"), "1", "Stub"))

    assert registry.resolve(ir) is not registry.resolve(ir)


def test_registry_rejects_duplicate_registration() -> None:
    registry = StrategyRegistry()
    registry.register("stub", "1", StubStrategy)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("stub", "1", StubStrategy)


def test_registry_rejects_unknown_strategy() -> None:
    registry = StrategyRegistry()
    ir = StrategyIR(StrategyId("missing"), "1", "Missing", (), ())
    with pytest.raises(KeyError, match="not registered"):
        registry.resolve(ir)
