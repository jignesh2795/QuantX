import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId, StrategySignal
from quantx.domain.value_objects import InstrumentId


def _signal(*, confidence: object = 1.0) -> StrategySignal:
    return StrategySignal(
        strategy_id=StrategyId("sma"),
        strategy_version="1",
        instrument=InstrumentId("NSE", "TCS"),
        action=SignalAction.BUY,
        confidence=confidence,  # type: ignore[arg-type]
        generated_at=datetime.now(UTC),
    )


def test_strategy_definition_requires_identity() -> None:
    with pytest.raises(ValueError, match="strategy id"):
        StrategyId("")


def test_signal_confidence_is_bounded() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _signal(confidence=1.2)


@pytest.mark.parametrize("confidence", [0, 0.0, 0.5, 1, 1.0])
def test_signal_confidence_accepts_inclusive_range(confidence: float | int) -> None:
    assert _signal(confidence=confidence).confidence == confidence


@pytest.mark.parametrize("confidence", [-0.0001, 1.0001, math.nan, math.inf, -math.inf])
def test_signal_confidence_rejects_out_of_range_and_non_finite(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        _signal(confidence=confidence)


@pytest.mark.parametrize("confidence", [True, False])
def test_signal_confidence_rejects_bool(confidence: bool) -> None:
    with pytest.raises(TypeError, match="confidence"):
        _signal(confidence=confidence)


@pytest.mark.parametrize("confidence", ["0.5", None, Decimal("0.5")])
def test_signal_confidence_rejects_unsupported_types(confidence: object) -> None:
    with pytest.raises(TypeError, match="confidence"):
        _signal(confidence=confidence)


def test_strategy_definition_is_market_neutral() -> None:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    definition = StrategyDefinition(
        strategy_id=StrategyId("mean-reversion"),
        version="1",
        name="Mean Reversion",
        market_contexts=(market,),
    )
    assert definition.strategy_id.value == "mean-reversion"
