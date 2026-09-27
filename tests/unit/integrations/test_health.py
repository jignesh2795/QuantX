from datetime import datetime, timezone

from quantx.integrations.health import (
    CapabilitySnapshot,
    ConnectionHealth,
    ConnectionHealthRegistry,
    ConnectionHealthSnapshot,
)
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import BrokerCapability, BrokerConnectionRef


def test_health_and_capabilities_are_tracked_per_connection() -> None:
    connection = BrokerConnectionRef(
        account_id=AccountId("acct1"),
        connection_id=BrokerConnectionId("acct1-broker1"),
        broker_id="broker1",
        market_context_id="NSE-EQUITY",
    )
    now = datetime.now(timezone.utc)
    registry = ConnectionHealthRegistry()

    registry.set_health(ConnectionHealthSnapshot(connection, ConnectionHealth.HEALTHY, now, 12))
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
