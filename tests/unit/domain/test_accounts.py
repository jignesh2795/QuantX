from quantx.domain.accounts import (
    Account,
    AccountId,
    AccountMarketProfile,
    AccountOwnerType,
    AccountRole,
    BrokerConnection,
    BrokerConnectionId,
    ConnectionStatus,
    Owner,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion


def india_equity_market() -> MarketContext:
    return MarketContext(
        region=MarketRegion.INDIA,
        family=MarketFamily.EQUITY,
        venue="NSE",
        country_code="IN",
    )


def test_family_can_own_multiple_accounts() -> None:
    owner = Owner("family-1", AccountOwnerType.FAMILY, "Household")
    first = Account(AccountId("acct-a"), owner.owner_id, "Member A", AccountRole.MEMBER, "INR")
    second = Account(AccountId("acct-b"), owner.owner_id, "Member B", AccountRole.MEMBER, "INR")

    assert first.owner_id == second.owner_id == owner.owner_id
    assert first.account_id != second.account_id


def test_one_account_can_have_multiple_broker_connections() -> None:
    account = Account(AccountId("acct-a"), "family-1", "Trading A", AccountRole.MEMBER, "INR")
    market = india_equity_market()

    dhan = BrokerConnection(
        BrokerConnectionId("conn-dhan"),
        account.account_id,
        "Dhan",
        "primary",
        market,
        ConnectionStatus.READY,
        frozenset({"equities", "websocket"}),
    )
    zerodha = BrokerConnection(
        BrokerConnectionId("conn-zerodha"),
        account.account_id,
        "Zerodha",
        "secondary",
        market,
        ConnectionStatus.READY,
        frozenset({"equities"}),
    )

    assert dhan.account_id == zerodha.account_id
    assert dhan.connection_id != zerodha.connection_id
    assert dhan.supports("websocket")
    assert not zerodha.supports("websocket")


def test_account_market_profile_is_separate_from_broker_connection() -> None:
    account = Account(AccountId("acct-a"), "owner-1", "Global Account", base_currency="INR")
    profile = AccountMarketProfile(account.account_id, india_equity_market())

    assert profile.account_id == account.account_id
    assert profile.market.venue == "NSE"
    assert profile.enabled
