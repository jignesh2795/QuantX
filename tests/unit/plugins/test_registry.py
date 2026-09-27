from __future__ import annotations

from dataclasses import dataclass

import pytest

from quantx.plugins import (
    PluginDescriptor,
    PluginId,
    PluginKind,
    PluginLifecycle,
    PluginRegistry,
)


@dataclass(frozen=True)
class FakePlugin:
    name: str


def _descriptor(
    value: str = "fake",
    *,
    kind: PluginKind = PluginKind.BROKER,
) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=PluginId(value),
        name="Fake Plugin",
        version="0.1",
        kind=kind,
        capabilities=frozenset({"ORDER_SUBMISSION"}),
        market_contexts=frozenset({"NSE"}),
    )


def test_registry_starts_plugins_discovered() -> None:
    registry = PluginRegistry()

    registration = registry.register(_descriptor(), lambda: FakePlugin("one"))

    assert registration.state is PluginLifecycle.DISCOVERED
    assert registry.get(PluginId("fake")) == registration


def test_registry_rejects_duplicate_plugin_ids() -> None:
    registry = PluginRegistry()
    registry.register(_descriptor(), lambda: FakePlugin("one"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_descriptor(), lambda: FakePlugin("two"))


def test_registry_lifecycle_and_factory_creation() -> None:
    registry = PluginRegistry()
    registry.register(_descriptor(), lambda: FakePlugin("ready"))

    registry.enable(PluginId("fake"))
    assert registry.get(PluginId("fake")).state is PluginLifecycle.ENABLED

    plugin = registry.create(PluginId("fake"))
    assert plugin == FakePlugin("ready")

    registry.mark_ready(PluginId("fake"))
    assert registry.get(PluginId("fake")).state is PluginLifecycle.READY


def test_registry_records_degraded_and_failed_reasons() -> None:
    registry = PluginRegistry()
    registry.register(_descriptor(), lambda: FakePlugin("one"))
    plugin_id = PluginId("fake")

    registry.enable(plugin_id)
    degraded = registry.mark_degraded(plugin_id, "transport unavailable")
    assert degraded.state is PluginLifecycle.DEGRADED
    assert degraded.failure_reason == "transport unavailable"

    registry.mark_ready(plugin_id)
    failed = registry.mark_failed(plugin_id, "health check failed")
    assert failed.state is PluginLifecycle.FAILED
    assert failed.failure_reason == "health check failed"

    registry.enable(plugin_id)
    assert registry.get(plugin_id).state is PluginLifecycle.ENABLED
    assert registry.get(plugin_id).failure_reason is None


def test_registry_requires_disabled_state_before_unregister() -> None:
    registry = PluginRegistry()
    plugin_id = PluginId("fake")
    registry.register(_descriptor(), lambda: FakePlugin("one"))
    registry.enable(plugin_id)

    with pytest.raises(ValueError, match="disabled"):
        registry.unregister(plugin_id)

    registry.disable(plugin_id)
    registry.unregister(plugin_id)

    with pytest.raises(KeyError, match="unknown plugin"):
        registry.get(plugin_id)


def test_registry_filters_by_plugin_kind() -> None:
    registry = PluginRegistry()
    registry.register(_descriptor("broker", kind=PluginKind.BROKER), lambda: FakePlugin("broker"))
    registry.register(
        _descriptor("strategy", kind=PluginKind.STRATEGY),
        lambda: FakePlugin("strategy"),
    )

    brokers = registry.list(PluginKind.BROKER)
    strategies = registry.list(PluginKind.STRATEGY)

    assert [item.descriptor.plugin_id.value for item in brokers] == ["broker"]
    assert [item.descriptor.plugin_id.value for item in strategies] == ["strategy"]


def test_registry_does_not_create_disabled_plugin() -> None:
    registry = PluginRegistry()
    plugin_id = PluginId("fake")
    registry.register(_descriptor(), lambda: FakePlugin("one"))

    with pytest.raises(RuntimeError, match="enabled or ready"):
        registry.create(plugin_id)

    registry.disable(plugin_id)
