from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnection, BrokerConnectionId, ConnectionStatus
from quantx.domain.enums import AssetClass
from quantx.domain.finance import AccountFinancialState, CapitalSourceType, BrokerConstraint
from quantx.domain.instruments import Instrument, InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.routing import RoutingCandidate, RoutingDecision, RoutingPolicyEvaluator
from quantx.domain.value_objects import Money, Quantity


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


def _financial(amount: str = "100000") -> AccountFinancialState:
    money = Money(Decimal(amount), "INR")
    zero = Money(Decimal("0"), "INR")
    return AccountFinancialState(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=money,
        available_cash=money,
        blocked_cash=zero,
        margin_used=zero,
        margin_available=money,
        buying_power=money,
    )


def _connection(account_id: AccountId, *, capabilities: frozenset[str]) -> BrokerConnection:
    return BrokerConnection(
        connection_id=BrokerConnectionId("dhan-a"),
        account_id=account_id,
        broker="dhan",
        profile_name="primary",
        market=_india_market(),
        status=ConnectionStatus.READY,
        capabilities=capabilities,
    )


def test_router_selects_matching_account_market_capabilities_and_capital() -> None:
    account_id = AccountId("account-a")
    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Money(Decimal("5000"), "INR"),
        quantity=Quantity(Decimal("10")),
        required_margin=Money(Decimal("2000"), "INR"),
        candidates=[
            RoutingCandidate(
                account_id,
                _connection(account_id, capabilities=frozenset({"equities", "orders"})),
                _financial(),
            )
        ],
        required_capabilities=frozenset({"equities", "orders"}),
    )

    assert result.decision == RoutingDecision.SELECT
    assert result.connection_id == BrokerConnectionId("dhan-a")


def test_router_rejects_capability_mismatch() -> None:
    account_id = AccountId("account-a")
    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Money(Decimal("5000"), "INR"),
        quantity=Quantity(Decimal("10")),
        required_margin=Money(Decimal("0"), "INR"),
        candidates=[
            RoutingCandidate(
                account_id,
                _connection(account_id, capabilities=frozenset({"equities"})),
                _financial(),
            )
        ],
        required_capabilities=frozenset({"equities", "options"}),
    )
    assert result.decision == RoutingDecision.REJECT


def test_router_skips_account_without_enough_margin() -> None:
    account_id = AccountId("account-a")
    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Money(Decimal("5000"), "INR"),
        quantity=Quantity(Decimal("10")),
        required_margin=Money(Decimal("150000"), "INR"),
        candidates=[
            RoutingCandidate(
                account_id,
                _connection(account_id, capabilities=frozenset({"equities", "orders"})),
                _financial(),
            )
        ],
        required_capabilities=frozenset({"equities", "orders"}),
    )
    assert result.decision == RoutingDecision.REJECT


def test_router_respects_explicit_broker_minimum() -> None:
    account_id = AccountId("account-a")
    result = RoutingPolicyEvaluator().evaluate(
        instrument=_instrument(),
        order_value=Money(Decimal("5000"), "INR"),
        quantity=Quantity(Decimal("10")),
        required_margin=Money(Decimal("0"), "INR"),
        candidates=[
            RoutingCandidate(
                account_id,
                _connection(account_id, capabilities=frozenset({"equities", "orders"})),
                _financial(),
                broker_constraints=(
                    BrokerConstraint(
                        name="broker-min-order",
                        description="Explicit broker minimum",
                        minimum_order_value=Decimal("10000"),
                    ),
                ),
            )
        ],
        required_capabilities=frozenset({"equities", "orders"}),
    )
    assert result.decision == RoutingDecision.REJECT
