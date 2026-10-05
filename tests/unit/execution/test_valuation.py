from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.positions import Position
from quantx.domain.value_objects import InstrumentId
from quantx.execution.valuation import Mark, MarkToMarketValuator, ValuationError


def _position(quantity: str, average: str) -> Position:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    instrument = Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=market,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )
    return Position(instrument, Decimal(quantity), Decimal(average))


def test_long_position_unrealized_pnl_uses_supplied_mark() -> None:
    result = MarkToMarketValuator().value_position(
        _position("10", "100"), mark_price=Decimal("110"), valuation_source="observed_quote"
    )
    assert result.market_value == Decimal("1100")
    assert result.unrealized_pnl == Decimal("100")


def test_short_position_unrealized_pnl_uses_supplied_mark() -> None:
    result = MarkToMarketValuator().value_position(
        _position("-10", "100"), mark_price=Decimal("90"), valuation_source="observed_quote"
    )
    assert result.unrealized_pnl == Decimal("100")


def test_missing_mark_is_not_invented() -> None:
    with pytest.raises(ValuationError, match="no mark price"):
        MarkToMarketValuator().value_position(
            _position("10", "100"), mark_price=None, valuation_source="observed_quote"
        )



def test_mark_preserves_timezone_aware_observation_time() -> None:
    observed_at = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)

    mark = Mark(
        instrument_id="NSE:TCS",
        price=Decimal("100"),
        source="historical-replay-last",
        observed_at=observed_at,
    )

    assert mark.observed_at == observed_at


def test_mark_rejects_naive_observation_time() -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        Mark(
            instrument_id="NSE:TCS",
            price=Decimal("100"),
            source="historical-replay-last",
            observed_at=datetime(2026, 1, 5, 9, 15),
        )
