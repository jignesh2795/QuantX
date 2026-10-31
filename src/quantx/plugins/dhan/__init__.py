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
from .host import (
    DhanHostConfig,
    DhanHostRuntime,
    build_dhan_host_runtime,
    build_dhan_risk_evidence_source,
)
from .market_data import DhanMarketDataAdapter
from .models import (
    DhanCredentials,
    DhanFundsSnapshot,
    DhanHoldingSnapshot,
    DhanHoldingsSnapshot,
    DhanInstrumentRef,
    DhanOrderRequest,
    DhanOrderResponse,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
    DhanProfileSnapshot,
)
from .recovery import DhanRecoveryEvidenceProvider, build_dhan_recovery_provider
from .risk_evidence import (
    DHAN_BROKER_ID,
    DhanRiskEvidenceSource,
)
from .session import DhanAuthenticationRejectedError, DhanTokenLifetimeError
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
    "DhanAuthenticationRejectedError",
    "DhanBrokerAdapter",
    "DhanCredentials",
    "DhanTokenLifetimeError",
    "DhanFundsSnapshot",
    "DhanHoldingSnapshot",
    "DhanHoldingsSnapshot",
    "DhanHostConfig",
    "DhanHostRuntime",
    "DhanInstrumentRef",
    "DhanMarketDataAdapter",
    "DhanOrderRequest",
    "DhanOrderResponse",
    "DhanPositionSnapshot",
    "DhanPositionsSnapshot",
    "DhanProfileSnapshot",
    "DhanRecoveryEvidenceProvider",
    "DhanRiskEvidenceSource",
    "DhanSDKTransport",
    "DhanTransport",
    "DHAN_CAPABILITIES",
    "DHAN_BROKER_ID",
    "DHAN_PLUGIN_DESCRIPTOR",
    "InMemoryDhanTransport",
    "build_dhan_host_runtime",
    "build_dhan_recovery_provider",
    "build_dhan_risk_evidence_source",
    "register_dhan_broker",
]
