from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnection, BrokerConnectionId, ConnectionStatus
from quantx.domain.finance import AccountFinancialState
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.enums import AssetClass
from quantx.domain.routing import RoutingCandidate, RoutingDecision, RoutingPolicyEvaluator
from quantx.domain.value_objects import Money


def _india_market() -> MarketContext:
    return MarketContext(
        region=MarketRegion.INDIA,
        family=MarketFamily.EQUITY,
        venue="NSE",
        country_code="IN",
    )


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=_india_market(),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _financial() -> AccountFinancialState:
    return AccountFinancialState(
        capital_source="paper_configured",
        cash_balance=Money(Decimal("100000"), "INR"),
        available_cash=Money(Decimal("100000"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("100000"), "INR"),
        buying_power=Money(Decimal("100000"), "INR"),
    )


def test_router_selects_only_matching_account_market_and_capabilities() -> None:
    account_id = AccountId("account-a")
    connection = BrokerConnection(
        connection_id=BrokerConnectionId("dhan-a"),
        account_id=account_id,
        broker="dhan",
        profile_name="primary",
        market=_india_market(),
        status=ConnectionStatus.READY,
        capabilities=frozenset({"equities", "orders"}),
    )
    candidate = RoutingCandidate(account_id, connection, _financial())

    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Decimal("5000"),
        required_margin=Decimal("0"),
        candidates=[candidate],
        required_capabilities=frozenset({"equities", "orders"}),
    )

    assert result.decision == RoutingDecision.SELECT
    assert result.connection_id == connection.connection_id


def test_router_rejects_capability_mismatch() -> None:
    account_id = AccountId("account-a")
    connection = BrokerConnection(
        connection_id=BrokerConnectionId("dhan-a"),
        account_id=account_id,
        broker="dhan",
        profile_name="primary",
        market=_india_market(),
        status=ConnectionStatus.READY,
        capabilities=frozenset({"equities"}),
    )
    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Decimal("5000"),
        required_margin=Decimal("0"),
        candidates=[RoutingCandidate(account_id, connection, _financial())],
        required_capabilities=frozenset({"equities", "options"}),
    )
    assert result.decision == RoutingDecision.REJECT
