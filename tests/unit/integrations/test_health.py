from datetime import UTC, datetime

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
)
from quantx.integrations.health import (
    CapabilitySnapshot,
    ConnectionHealth,
    ConnectionHealthRegistry,
    ConnectionHealthSnapshot,
)


def test_health_and_capabilities_are_tracked_per_connection() -> None:
    connection = BrokerConnectionRef(
        account_id=AccountId("acct1"),
        connection_id=BrokerConnectionId("acct1-broker1"),
        broker_id="broker1",
        market_context_id="NSE-EQUITY",
    )
    now = datetime.now(UTC)
    registry = ConnectionHealthRegistry()

    registry.set_health(
        ConnectionHealthSnapshot(connection, ConnectionHealth.HEALTHY, now, 12)
    )
    registry.set_capabilities(
        CapabilitySnapshot(
            connection,
            frozenset({BrokerCapability.MARKET_DATA, BrokerCapability.ORDER_SUBMISSION}),
            now,
            "caps-v1",
        )
    )

    assert registry.health(connection).status is ConnectionHealth.HEALTHY
    assert BrokerCapability.ORDER_SUBMISSION in registry.capabilities(connection).capabilities


def test_health_and_capabilities_are_isolated_by_full_connection_ref() -> None:
    connection_a = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("shared-id"),
        "broker-a",
        "NSE-EQUITY",
    )
    connection_b = BrokerConnectionRef(
        AccountId("acct-2"),
        BrokerConnectionId("shared-id"),
        "broker-b",
        "NSE-EQUITY",
    )
    now = datetime.now(UTC)
    registry = ConnectionHealthRegistry()

    registry.set_health(
        ConnectionHealthSnapshot(connection_a, ConnectionHealth.HEALTHY, now, 10)
    )
    registry.set_health(
        ConnectionHealthSnapshot(connection_b, ConnectionHealth.UNAVAILABLE, now, 20)
    )
    registry.set_capabilities(
        CapabilitySnapshot(
            connection_a,
            frozenset({BrokerCapability.ORDER_SUBMISSION}),
            now,
            "a-v1",
        )
    )
    registry.set_capabilities(
        CapabilitySnapshot(
            connection_b,
            frozenset({BrokerCapability.BALANCES}),
            now,
            "b-v1",
        )
    )

    assert registry.health(connection_a).status is ConnectionHealth.HEALTHY
    assert registry.health(connection_b).status is ConnectionHealth.UNAVAILABLE
    assert registry.capabilities(connection_a).capabilities == frozenset(
        {BrokerCapability.ORDER_SUBMISSION}
    )
    assert registry.capabilities(connection_b).capabilities == frozenset(
        {BrokerCapability.BALANCES}
    )
