"""Dhan broker plugin with isolated SDK transport."""

from quantx.plugins import (
    PluginDescriptor,
    PluginFactory,
    PluginId,
    PluginKind,
    PluginRegistration,
    PluginRegistry,
)

from .adapter import DhanBrokerAdapter
from .capabilities import DHAN_CAPABILITIES
from .models import (
    DhanCredentials,
    DhanInstrumentRef,
    DhanOrderRequest,
    DhanOrderResponse,
)
from .transport import DhanSDKTransport, DhanTransport, InMemoryDhanTransport

DHAN_PLUGIN_DESCRIPTOR = PluginDescriptor(
    plugin_id=PluginId("dhan"),
    name="Dhan",
    version="0.1",
    kind=PluginKind.BROKER,
    capabilities=frozenset(capability.value for capability in DHAN_CAPABILITIES.values),
    market_contexts=frozenset({"NSE_EQ", "BSE_EQ", "NSE_FNO", "BSE_FNO", "MCX_COMM"}),
)


def register_dhan_broker(
    registry: PluginRegistry,
    factory: PluginFactory,
) -> PluginRegistration:
    return registry.register(DHAN_PLUGIN_DESCRIPTOR, factory)


__all__ = [
    "DhanBrokerAdapter",
    "DhanCredentials",
    "DhanInstrumentRef",
    "DhanOrderRequest",
    "DhanOrderResponse",
    "DhanSDKTransport",
    "DhanTransport",
    "DHAN_CAPABILITIES",
    "DHAN_PLUGIN_DESCRIPTOR",
    "InMemoryDhanTransport",
    "register_dhan_broker",
]
