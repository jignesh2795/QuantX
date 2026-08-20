from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.positions import Position
from quantx.execution.valuation import MarkToMarketValuator, ValuationError


def _position(quantity: str, average: str) -> Position:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    instrument = Instrument("nse:tcs", "TCS", AssetClass.EQUITY, market, Decimal("0.01"), Decimal("1"), Decimal("1"))
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
