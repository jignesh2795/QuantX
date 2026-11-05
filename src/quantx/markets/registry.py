"""Caller-populated market module registry."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.instruments import MarketContext, MarketRegion

from .common.module_base import MarketModuleBase
from .common.protocol import MarketModule


class UnsupportedMarketError(ValueError):
    """Raised when a market-dependent operation has no implemented module."""


@dataclass(slots=True)
class _RegisteredModule:
    module: MarketModule


class MarketRegistry:
    """Registry populated only by explicit caller registration."""

    def __init__(self) -> None:
        self._modules: dict[MarketRegion, MarketModule] = {}

    def register(self, module: MarketModule) -> None:
        if not isinstance(module, MarketModuleBase):
            raise ValueError("module must be a MarketModuleBase")
        if not hasattr(module, "region") or not hasattr(module, "market_contexts"):
            raise ValueError("module must satisfy MarketModule")
        region = getattr(module, "region", None)
        if not isinstance(region, MarketRegion):
            raise ValueError("region must be a MarketRegion")
        contexts = getattr(module, "market_contexts", None)
        if not isinstance(contexts, frozenset) or not contexts:
            raise ValueError("market_contexts must be a non-empty frozenset")
        if any(not isinstance(context, MarketContext) for context in contexts):
            raise ValueError("market_contexts must contain MarketContext values")
        if any(context.region is not region for context in contexts):
            raise ValueError("every market context must belong to the module region")
        market_pack_id = getattr(module, "market_pack_id", None)
        if not isinstance(market_pack_id, str) or not market_pack_id.strip():
            raise ValueError("market_pack_id must be a non-empty string")
        rule_version = getattr(module, "rule_version", None)
        if not isinstance(rule_version, str) or not rule_version.strip():
            raise ValueError("rule_version must be a non-empty string")
        if region in self._modules:
            raise ValueError(f"market module already registered for {region.value}")
        self._modules[region] = module

    def get(self, region: MarketRegion) -> MarketModule | None:
        if not isinstance(region, MarketRegion):
            raise ValueError("region must be a MarketRegion")
        return self._modules.get(region)

    def get_for_context(self, context: MarketContext) -> MarketModule | None:
        if not isinstance(context, MarketContext):
            raise ValueError("context must be a MarketContext")
        module = self._modules.get(context.region)
        if module is None:
            return None
        if context not in module.market_contexts:
            return None
        return module

    def available(self) -> frozenset[MarketRegion]:
        return frozenset(self._modules)

    def __contains__(self, region: object) -> bool:
        return isinstance(region, MarketRegion) and region in self._modules
