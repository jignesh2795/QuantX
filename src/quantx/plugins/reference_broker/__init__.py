"""Deterministic reference broker plugin for adapter conformance."""

from quantx.integrations.brokers import BrokerCapability
from quantx.plugins import (
    PluginDescriptor,
    PluginFactory,
    PluginId,
    PluginKind,
    PluginRegistry,
    PluginRegistration,
)

from .adapter import ReferenceBrokerAdapter
from .transport import (
    InMemoryReferenceBrokerTransport,
    ReferenceBrokerTransport,
    ReferenceOrderRequest,
    ReferenceOrderResponse,
)

REFERENCE_BROKER_DESCRIPTOR = PluginDescriptor(
    plugin_id=PluginId("reference-broker"),
    name="QuantX Reference Broker",
    version="0.1",
    kind=PluginKind.BROKER,
    capabilities=frozenset(capability.value for capability in BrokerCapability),
)


def register_reference_broker(
    registry: PluginRegistry,
    factory: PluginFactory,
) -> PluginRegistration:
    """Register the reference broker without exposing transport dependencies to core."""
    return registry.register(REFERENCE_BROKER_DESCRIPTOR, factory)


__all__ = [
    "InMemoryReferenceBrokerTransport",
    "ReferenceBrokerAdapter",
    "ReferenceBrokerTransport",
    "ReferenceOrderRequest",
    "ReferenceOrderResponse",
    "REFERENCE_BROKER_DESCRIPTOR",
    "register_reference_broker",
]
