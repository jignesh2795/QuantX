"""Capability declaration for the Dhan plugin."""

from quantx.integrations.brokers import BrokerCapability, CapabilitySet
DHAN_CAPABILITIES = CapabilitySet(
    frozenset(
        {
            BrokerCapability.ORDER_SUBMISSION,
            BrokerCapability.ORDER_CANCELLATION,
        }
    )
)
