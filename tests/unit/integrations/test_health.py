from datetime import datetime, timezone

from quantx.integrations.health import (
    CapabilitySnapshot,
    ConnectionHealth,
    ConnectionHealthRegistry,
    ConnectionHealthSnapshot,
)
from quantx.integrations.brokers import BrokerConnectionRef, Capability


def test_health_and_capabilities_are_tracked_per_connection() -> None:
    connection = BrokerConnectionRef(
        connection_id="acct1-broker1",
        account_id="acct1",
        broker_id="broker1",
        environment="PAPER",
    )
    now = datetime.now(timezone.utc)
    registry = ConnectionHealthRegistry()

    registry.set_health(ConnectionHealthSnapshot(connection, ConnectionHealth.HEALTHY, now, 12))
    registry.set_capabilities(
        CapabilitySnapshot(
            connection,
            frozenset({Capability.MARKET_DATA, Capability.ORDER_SUBMISSION}),
            now,
            "caps-v1",
        )
    )

    assert registry.health(connection).status is ConnectionHealth.HEALTHY
    assert Capability.ORDER_SUBMISSION in registry.capabilities(connection).capabilities
