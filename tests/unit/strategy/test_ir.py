from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.strategy.compiler import StrategyCompiler


def test_compile_normalizes_parameter_order() -> None:
    definition = StrategyDefinition(
        strategy_id=StrategyId("buy-and-hold"),
        version="1",
        name="Buy and Hold",
        market_contexts=(MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),),
        parameters={"quantity": "2", "entry": "first"},
    )

    ir = StrategyCompiler.compile(definition)

    assert ir.parameters == (("entry", "first"), ("quantity", "2"))
    assert ir.parameter("quantity") == "2"


def test_compile_is_deterministic_for_equivalent_mappings() -> None:
    kwargs = dict(
        strategy_id=StrategyId("sma"),
        version="1",
        name="SMA",
        parameters={"slow": "20", "fast": "5"},
    )
    assert StrategyCompiler.compile(StrategyDefinition(**kwargs)) == StrategyCompiler.compile(
        StrategyDefinition(**{**kwargs, "parameters": {"fast": "5", "slow": "20"}})
    )
