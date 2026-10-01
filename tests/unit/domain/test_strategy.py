from datetime import datetime, timezone

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId, StrategySignal
from quantx.domain.value_objects import InstrumentId


def test_strategy_definition_requires_identity() -> None:
    with pytest.raises(ValueError, match="strategy id"):
        StrategyId("")


def test_signal_confidence_is_bounded() -> None:
    with pytest.raises(ValueError, match="confidence"):
        StrategySignal(
            strategy_id=StrategyId("sma"),
            strategy_version="1",
            instrument=InstrumentId("NSE", "TCS"),
            action=SignalAction.BUY,
            confidence=1.2,
            generated_at=datetime.now(timezone.utc),
        )


def test_strategy_definition_is_market_neutral() -> None:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    definition = StrategyDefinition(
        strategy_id=StrategyId("mean-reversion"),
        version="1",
        name="Mean Reversion",
        market_contexts=(market,),
    )
    assert definition.strategy_id.value == "mean-reversion"
