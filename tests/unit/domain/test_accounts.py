from quantx.domain.accounts import (
    Account,
    AccountId,
    AccountOwnerType,
    AccountRole,
    BrokerConnection,
    BrokerConnectionId,
)


def test_multiple_accounts_can_use_distinct_broker_connections() -> None:
    family = Account(
        account_id=AccountId("family-main"),
        display_name="Family Trading",
        owner_type=AccountOwnerType.FAMILY,
    )
    member = Account(
        account_id=AccountId("member-1"),
        display_name="Member One",
        owner_type=AccountOwnerType.FAMILY,
        role=AccountRole.MEMBER,
    )

    dhan = BrokerConnection(
        connection_id=BrokerConnectionId("dhan-family"),
        account_id=family.account_id,
        broker="dhan",
        profile_name="family-dhan",
    )
    zerodha = BrokerConnection(
        connection_id=BrokerConnectionId("zerodha-member-1"),
        account_id=member.account_id,
        broker="zerodha",
        profile_name="member-zerodha",
    )

    assert dhan.account_id == family.account_id
    assert zerodha.account_id == member.account_id
    assert dhan.connection_id != zerodha.connection_id


def test_same_account_can_have_more_than_one_broker_connection() -> None:
    account = Account(
        account_id=AccountId("trading-1"),
        display_name="Trading Account",
        owner_type=AccountOwnerType.INDIVIDUAL,
    )

    first = BrokerConnection(
        connection_id=BrokerConnectionId("conn-a"),
        account_id=account.account_id,
        broker="dhan",
        profile_name="dhan-primary",
    )
    second = BrokerConnection(
        connection_id=BrokerConnectionId("conn-b"),
        account_id=account.account_id,
        broker="zerodha",
        profile_name="zerodha-primary",
    )

    assert first.account_id == second.account_id
    assert first.broker != second.broker
    assert first.connection_id != second.connection_id
