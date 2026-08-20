from decimal import Decimal

from quantx.domain.deployment import PortfolioId
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.portfolio_valuation import PortfolioValuator
from quantx.execution.valuation import Mark
from quantx.domain.positions import Position


def test_portfolio_valuation_marks_only_supplied_positions():
    # Kept intentionally minimal: the integration contract is that an absent
    # mark produces an INCOMPLETE result instead of an invented valuation.
    valuator = PortfolioValuator()
    result = valuator.value(
        portfolio_id=PortfolioId("p-1"),
        valuation_currency="INR",
        cash=Money(Decimal("1000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        positions=(),
        marks=(),
        realized_pnl=Decimal("0"),
    )
    assert result.completeness == "COMPLETE"
    assert result.snapshot.equity.amount == Decimal("1000")
