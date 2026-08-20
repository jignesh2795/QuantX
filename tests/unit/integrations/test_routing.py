from uuid import uuid4

import pytest

from quantx.integrations.brokers import BrokerCapability, BrokerConnectionRef, BrokerDescriptor, CapabilitySet
from quantx.integrations.account_registry import AccountConnectionRegistry, RegisteredConnection
from quantx.integrations.routing import (
    AccountAwareRouter,
    FailoverReason,
    RoutingDisposition,
    RoutingRequest,
)


class FakeAdapter:
    def __init__(self, connection, capabilities, healthy=True):
        self._connection = connection
        self._capabilities = CapabilitySet(frozenset(capabilities))
        self._healthy = healthy
        self.descriptor = BrokerDescriptor("fake", "Fake", self._capabilities, "1")

    @property
    def connection(self):
        return self._connection

    def health(self):
        return self._healthy

    def capabilities(self):
        return self._capabilities


def register(registry, account_id, market, healthy=True):
    ref = BrokerConnectionRef(account_id, uuid4(), "fake", market)
    item = RegisteredConnection(
        ref,
        FakeAdapter(ref, {BrokerCapability.ORDER_SUBMISSION}, healthy),
    )
    registry.register(item)
    return item


def test_routes_same_account_and_market():
    registry = AccountConnectionRegistry()
    account = uuid4()
    item = register(registry, account, "NSE")

    decision = AccountAwareRouter(registry).route(
        RoutingRequest(account, "NSE", frozenset({BrokerCapability.ORDER_SUBMISSION}))
    )

    assert decision.disposition is RoutingDisposition.ROUTED
    assert decision.connection == item


def test_never_fails_over_to_another_account():
    registry = AccountConnectionRegistry()
    requested = uuid4()
    other = uuid4()
    register(registry, other, "NSE")

    preferred_ref = BrokerConnectionRef(requested, uuid4(), "fake", "NSE")
    decision = AccountAwareRouter(registry).route(
        RoutingRequest(
            requested,
            "NSE",
            frozenset({BrokerCapability.ORDER_SUBMISSION}),
            preferred_connection_id=preferred_ref.connection_id,
        )
    )

    assert decision.disposition is RoutingDisposition.FAILOVER_BLOCKED
    assert decision.reason is FailoverReason.ACCOUNT_MISMATCH


def test_never_fails_over_across_market_context():
    registry = AccountConnectionRegistry()
    account = uuid4()
    register(registry, account, "BINANCE")

    decision = AccountAwareRouter(registry).route(
        RoutingRequest(account, "NSE", frozenset({BrokerCapability.ORDER_SUBMISSION}))
    )

    assert decision.disposition is RoutingDisposition.NO_ROUTE


def test_unhealthy_preferred_connection_can_failover_same_account_and_market():
    registry = AccountConnectionRegistry()
    account = uuid4()
    preferred = register(registry, account, "NSE", healthy=False)
    fallback = register(registry, account, "NSE", healthy=True)

    decision = AccountAwareRouter(registry).route(
        RoutingRequest(
            account,
            "NSE",
            frozenset({BrokerCapability.ORDER_SUBMISSION}),
            preferred_connection_id=preferred.ref.connection_id,
        )
    )

    assert decision.disposition is RoutingDisposition.ROUTED
    assert decision.connection == fallback


def test_failover_can_be_disabled():
    registry = AccountConnectionRegistry()
    account = uuid4()
    preferred = register(registry, account, "NSE", healthy=False)
    register(registry, account, "NSE", healthy=True)

    decision = AccountAwareRouter(registry).route(
        RoutingRequest(
            account,
            "NSE",
            frozenset({BrokerCapability.ORDER_SUBMISSION}),
            preferred_connection_id=preferred.ref.connection_id,
            allow_failover=False,
        )
    )

    assert decision.disposition is RoutingDisposition.FAILOVER_BLOCKED
    assert decision.reason is FailoverReason.HEALTH_UNAVAILABLE
