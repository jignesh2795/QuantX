"""Local-first plugin registry and lifecycle boundary.

The registry stores plugin metadata and factories only. Secrets and live broker
credentials must remain owned by the concrete plugin/runtime integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import FrozenSet, Protocol


class PluginKind(StrEnum):
    BROKER = "BROKER"
    MARKET_DATA = "MARKET_DATA"
    STRATEGY = "STRATEGY"
    RESEARCH = "RESEARCH"
    RISK = "RISK"
    UI = "UI"


class PluginLifecycle(StrEnum):
    DISCOVERED = "DISCOVERED"
    ENABLED = "ENABLED"
    READY = "READY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PluginId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("plugin id must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    plugin_id: PluginId
    name: str
    version: str
    kind: PluginKind
    capabilities: FrozenSet[str] = frozenset()
    market_contexts: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("plugin name must not be empty")
        if not self.version.strip():
            raise ValueError("plugin version must not be empty")


class PluginFactory(Protocol):
    def __call__(self) -> object: ...


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    descriptor: PluginDescriptor
    factory: PluginFactory
    state: PluginLifecycle = PluginLifecycle.DISCOVERED
    failure_reason: str | None = None


class PluginRegistry:
    """Explicit in-process registry for deterministic local plugin management."""

    def __init__(self) -> None:
        self._registrations: dict[PluginId, PluginRegistration] = {}

    def register(
        self,
        descriptor: PluginDescriptor,
        factory: PluginFactory,
    ) -> PluginRegistration:
        if descriptor.plugin_id in self._registrations:
            raise ValueError(f"plugin already registered: {descriptor.plugin_id}")
        registration = PluginRegistration(descriptor=descriptor, factory=factory)
        self._registrations[descriptor.plugin_id] = registration
        return registration

    def unregister(self, plugin_id: PluginId) -> None:
        registration = self.get(plugin_id)
        if registration.state in {
            PluginLifecycle.ENABLED,
            PluginLifecycle.READY,
            PluginLifecycle.DEGRADED,
        }:
            raise ValueError("enabled plugin must be disabled before unregistering")
        del self._registrations[plugin_id]

    def get(self, plugin_id: PluginId) -> PluginRegistration:
        try:
            return self._registrations[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    def list(self, kind: PluginKind | None = None) -> tuple[PluginRegistration, ...]:
        registrations = tuple(self._registrations.values())
        if kind is None:
            return registrations
        return tuple(
            registration for registration in registrations if registration.descriptor.kind is kind
        )

    def transition(
        self,
        plugin_id: PluginId,
        state: PluginLifecycle,
        *,
        reason: str | None = None,
    ) -> PluginRegistration:
        registration = self.get(plugin_id)
        updated = replace(
            registration,
            state=state,
            failure_reason=reason
            if state
            in {
                PluginLifecycle.DEGRADED,
                PluginLifecycle.FAILED,
            }
            else None,
        )
        self._registrations[plugin_id] = updated
        return updated

    def enable(self, plugin_id: PluginId) -> PluginRegistration:
        registration = self.get(plugin_id)
        if registration.state not in {
            PluginLifecycle.DISCOVERED,
            PluginLifecycle.DISABLED,
            PluginLifecycle.FAILED,
        }:
            raise ValueError(f"plugin cannot be enabled from {registration.state}")
        return self.transition(plugin_id, PluginLifecycle.ENABLED)

    def mark_ready(self, plugin_id: PluginId) -> PluginRegistration:
        registration = self.get(plugin_id)
        if registration.state not in {
            PluginLifecycle.ENABLED,
            PluginLifecycle.DEGRADED,
        }:
            raise ValueError(f"plugin cannot become ready from {registration.state}")
        return self.transition(plugin_id, PluginLifecycle.READY)

    def mark_degraded(self, plugin_id: PluginId, reason: str) -> PluginRegistration:
        if not reason.strip():
            raise ValueError("degraded reason must not be empty")
        registration = self.get(plugin_id)
        if registration.state not in {
            PluginLifecycle.ENABLED,
            PluginLifecycle.READY,
        }:
            raise ValueError(f"plugin cannot become degraded from {registration.state}")
        return self.transition(plugin_id, PluginLifecycle.DEGRADED, reason=reason)

    def mark_failed(self, plugin_id: PluginId, reason: str) -> PluginRegistration:
        if not reason.strip():
            raise ValueError("failure reason must not be empty")
        return self.transition(plugin_id, PluginLifecycle.FAILED, reason=reason)

    def disable(self, plugin_id: PluginId) -> PluginRegistration:
        registration = self.get(plugin_id)
        if registration.state is PluginLifecycle.DISABLED:
            return registration
        return self.transition(plugin_id, PluginLifecycle.DISABLED)

    def create(self, plugin_id: PluginId) -> object:
        registration = self.get(plugin_id)
        if registration.state not in {
            PluginLifecycle.ENABLED,
            PluginLifecycle.READY,
        }:
            raise RuntimeError(
                f"plugin must be enabled or ready before creation: {registration.state}"
            )
        return registration.factory()
