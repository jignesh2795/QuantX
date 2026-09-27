from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import (
    BrokerCapability,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)


def test_capability_set_supports_required_subset() -> None:
    capabilities = CapabilitySet(
        frozenset({BrokerCapability.ORDER_SUBMISSION, BrokerCapability.BALANCES})
    )
    assert capabilities.supports(BrokerCapability.ORDER_SUBMISSION)
    assert capabilities.require(frozenset({BrokerCapability.ORDER_SUBMISSION}))
    assert not capabilities.require(
        frozenset({BrokerCapability.ORDER_SUBMISSION, BrokerCapability.OPTIONS})
    )


def test_connection_is_account_scoped() -> None:
    connection = BrokerConnectionRef(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        broker_id="example",
        market_context_id="india-equity",
    )
    assert connection.account_id == AccountId("acct-1")
    assert connection.connection_id == BrokerConnectionId("conn-1")


def test_descriptor_keeps_capabilities_and_version_explicit() -> None:
    descriptor = BrokerDescriptor(
        broker_id="example",
        display_name="Example Broker",
        capabilities=CapabilitySet(frozenset({BrokerCapability.MARKET_DATA})),
        adapter_version="1.0.0",
    )
    assert descriptor.capabilities.supports(BrokerCapability.MARKET_DATA)
    assert descriptor.adapter_version == "1.0.0"
