import math
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

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
    signal = _signal(confidence=confidence)

    assert signal.confidence == confidence
    assert type(signal.confidence) is float


@pytest.mark.parametrize(
    "confidence",
    [Fraction(0, 1), Fraction(1, 2), Fraction(1, 1)],
)
def test_signal_confidence_normalizes_fraction_to_float(confidence: Fraction) -> None:
    signal = _signal(confidence=confidence)

    assert signal.confidence == float(confidence)
    assert type(signal.confidence) is float


@pytest.mark.parametrize(
    "confidence",
    [-0.0001, 1.0001, math.nan, math.inf, -math.inf, Fraction(3, 2), Fraction(10**400, 1)],
)
def test_signal_confidence_rejects_out_of_range_and_non_finite(confidence: object) -> None:
    with pytest.raises(ValueError, match="confidence"):
        _signal(confidence=confidence)


@pytest.mark.parametrize("confidence", [True, False])
def test_signal_confidence_rejects_bool(confidence: bool) -> None:
    with pytest.raises(TypeError, match="bool"):
        _signal(confidence=confidence)


def test_signal_confidence_rejects_decimal_with_accurate_type_error() -> None:
    with pytest.raises(TypeError, match="Decimal") as error:
        _signal(confidence=Decimal("0.5"))

    assert "numbers.Real" in str(error.value)


@pytest.mark.parametrize(
    ("confidence", "type_name"),
    [("0.5", "str"), (None, "NoneType"), (1 + 2j, "complex")],
)
def test_signal_confidence_rejects_unsupported_types_with_accurate_error(
    confidence: object,
    type_name: str,
) -> None:
    with pytest.raises(TypeError, match=type_name) as error:
        _signal(confidence=confidence)

    assert "numbers.Real" in str(error.value)


class _MisleadingFraction(Fraction):
    """A Real whose comparisons lie about the value returned by float()."""

    def __le__(self, other: object) -> bool:
        return True

    def __ge__(self, other: object) -> bool:
        return True

    def __float__(self) -> float:
        return 5.0


def test_signal_confidence_validates_the_canonical_float() -> None:
    misleading = _MisleadingFraction(1, 2)

    # Its own comparisons claim it is in range, but the stored representation
    # would be 5.0. The domain boundary must validate the canonical float.
    assert isinstance(misleading, Fraction)
    assert 0.0 <= misleading <= 1.0
    assert float(misleading) == 5.0

    with pytest.raises(ValueError, match="confidence"):
        _signal(confidence=misleading)


def test_strategy_definition_is_market_neutral() -> None:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    definition = StrategyDefinition(
        strategy_id=StrategyId("mean-reversion"),
        version="1",
        name="Mean Reversion",
        market_contexts=(market,),
    )
    assert definition.strategy_id.value == "mean-reversion"
