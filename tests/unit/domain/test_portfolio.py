from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import PortfolioId
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.portfolio import Portfolio, PortfolioSnapshot, PositionLedger
from quantx.domain.value_objects import Money


def india_equity_market() -> MarketContext:
    return MarketContext(
        region=MarketRegion.INDIA,
        family=MarketFamily.EQUITY,
        venue="NSE",
        country_code="IN",
    )


def test_logical_portfolio_can_span_multiple_accounts() -> None:
    account_a = AccountId("family-a")
    account_b = AccountId("family-b")

    portfolio = Portfolio(
        portfolio_id=PortfolioId("india-long-term"),
        name="India Long Term",
        account_ids=(account_a, account_b),
        market=india_equity_market(),
    )

    assert portfolio.contains_account(account_a)
    assert portfolio.contains_account(account_b)


def test_portfolio_snapshot_equity_is_explicit_cash_plus_market_value() -> None:
    snapshot = PortfolioSnapshot(
        portfolio_id=PortfolioId("p1"),
        valuation_currency="INR",
        cash=Money(Decimal("100000"), "INR"),
        market_value=Money(Decimal("25000"), "INR"),
        realized_pnl=Money(Decimal("1500"), "INR"),
        unrealized_pnl=Money(Decimal("2500"), "INR"),
        margin_used=Money(Decimal("5000"), "INR"),
    )

    assert snapshot.equity.amount == Decimal("125000")


def test_snapshot_rejects_mixed_currencies() -> None:
    try:
        PortfolioSnapshot(
            portfolio_id=PortfolioId("p1"),
            valuation_currency="INR",
            cash=Money(Decimal("1000"), "INR"),
            market_value=Money(Decimal("100"), "USD"),
            realized_pnl=Money(Decimal("0"), "INR"),
            unrealized_pnl=Money(Decimal("0"), "INR"),
            margin_used=Money(Decimal("0"), "INR"),
        )
    except ValueError:
        return
    raise AssertionError("mixed currencies must be rejected")
