"""Package-level import boundary regressions for the QuantX modular monolith.

The matrix records the intended dependency direction. Deferred entries are
separate so a known violation cannot hide behind a broad allowed edge, and so
removing the violation requires deleting its registry entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.unit.architecture._import_graph import (
    build_import_graph,
    extract_imports,
    find_package_cycles,
)

_ALLOWED_RUNTIME: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "ports": frozenset({"domain"}),
    "execution": frozenset({"domain", "ports"}),
    "integrations": frozenset({"domain", "execution", "ports"}),
    "persistence": frozenset({"domain", "execution", "ports", "research"}),
    "research": frozenset({"domain", "ports"}),
    "strategy": frozenset({"domain", "execution", "ports"}),
    "india": frozenset({"domain", "ports"}),
    "application": frozenset(
        {
            "domain",
            "execution",
            "integrations",
            "persistence",
            "ports",
            "research",
            "strategy",
        }
    ),
    "plugins": frozenset({"application", "domain", "execution", "integrations", "ports"}),
}


@dataclass(frozen=True, slots=True)
class DeferredDependency:
    issue: str
    reason: str
    removal_condition: str


_DEFERRED_RUNTIME: dict[tuple[str, str], DeferredDependency] = {
    ("india", "research"): DeferredDependency(
        issue="#181",
        reason=(
            "The India historical normalizer consumes research-owned calendar and "
            "observation contracts; relocating it is a separate follow-up slice."
        ),
        removal_condition=(
            "Move the India historical adapter beside the research contracts and "
            "delete the india -> research import."
        ),
    ),
    ("strategy", "research"): DeferredDependency(
        issue="#181",
        reason=(
            "The strategy replay evaluation consumes the research-owned ReplayFrame; "
            "moving the method is a separate follow-up slice."
        ),
        removal_condition=(
            "Relocate evaluate_replay_frame to the application replay boundary and "
            "delete the strategy -> research import."
        ),
    ),
}

_DEFERRED_TYPE_ONLY: dict[tuple[str, str], DeferredDependency] = {
    ("ports", "execution"): DeferredDependency(
        issue="#181",
        reason=(
            "Port contracts reference canonical execution records only in postponed "
            "annotations; this removes the runtime import without relocating "
            "receipt/idempotency/quarantine ownership."
        ),
        removal_condition=(
            "Delete this entry when the canonical execution records move below the "
            "ports boundary or a successor ADR accepts the type-only exception."
        ),
    ),
}


def test_runtime_package_edges_are_allowed_or_registered() -> None:
    graph = build_import_graph()
    offenders: list[str] = []
    for edge in graph.by_kind(type_only=False):
        pair = (edge.source_package, edge.target_package)
        if (
            edge.target_package not in _ALLOWED_RUNTIME.get(edge.source_package, frozenset())
            and pair not in _DEFERRED_RUNTIME
        ):
            offenders.append(edge.describe())
    assert offenders == [], "unregistered runtime package dependency:\n" + "\n".join(offenders)


def test_type_only_package_edges_are_allowed_or_registered() -> None:
    graph = build_import_graph()
    offenders: list[str] = []
    for edge in graph.by_kind(type_only=True):
        pair = (edge.source_package, edge.target_package)
        if (
            edge.target_package not in _ALLOWED_RUNTIME.get(edge.source_package, frozenset())
            and pair not in _DEFERRED_TYPE_ONLY
        ):
            offenders.append(edge.describe())
    assert offenders == [], "unregistered type-only package dependency:\n" + "\n".join(offenders)


def test_runtime_graph_has_no_package_cycles() -> None:
    graph = build_import_graph()
    cycles = find_package_cycles(graph.package_pairs(type_only=False))
    described = [" -> ".join((*cycle, cycle[0])) for cycle in cycles]
    assert cycles == (), "runtime package cycle:\n" + "\n".join(described)


def test_domain_has_no_outbound_package_dependencies() -> None:
    graph = build_import_graph()
    offenders = [edge.describe() for edge in graph.edges if edge.source_package == "domain"]
    assert offenders == [], "domain must not import other packages:\n" + "\n".join(offenders)


def test_deferred_runtime_registry_matches_observed_edges() -> None:
    graph = build_import_graph()
    observed = {
        (edge.source_package, edge.target_package) for edge in graph.by_kind(type_only=False)
    }
    remaining = observed & set(_DEFERRED_RUNTIME)
    assert remaining == set(_DEFERRED_RUNTIME), (
        "deferred runtime registry is stale; expected "
        f"{sorted(set(_DEFERRED_RUNTIME))}, observed {sorted(remaining)}"
    )
    for pair, dependency in _DEFERRED_RUNTIME.items():
        assert dependency.issue.startswith("#"), pair
        assert dependency.reason.strip(), pair
        assert dependency.removal_condition.strip(), pair


def test_deferred_type_only_registry_matches_observed_edges() -> None:
    graph = build_import_graph()
    observed = {
        (edge.source_package, edge.target_package) for edge in graph.by_kind(type_only=True)
    }
    remaining = observed & set(_DEFERRED_TYPE_ONLY)
    assert remaining == set(_DEFERRED_TYPE_ONLY), (
        "deferred type-only registry is stale; expected "
        f"{sorted(set(_DEFERRED_TYPE_ONLY))}, observed {sorted(remaining)}"
    )


def test_cycle_detector_finds_synthetic_cycle() -> None:
    assert find_package_cycles(
        {("alpha", "beta"), ("beta", "gamma"), ("gamma", "alpha"), ("beta", "delta")}
    ) == (("alpha", "beta", "gamma"),)
    assert find_package_cycles({("alpha", "beta"), ("beta", "gamma")}) == ()


def test_extractor_separates_runtime_and_type_checking_imports() -> None:
    source = """
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import ports

from ..ports import broker
import quantx.strategy.runtime
"""
    known_modules = frozenset(
        {
            "quantx.architecture.demo",
            "quantx.execution",
            "quantx.execution.ports",
            "quantx.ports",
            "quantx.ports.broker",
            "quantx.strategy",
            "quantx.strategy.runtime",
        }
    )
    edges = extract_imports(
        source,
        module="quantx.architecture.demo",
        known_modules=known_modules,
    )
    observed = {(edge.target_package, edge.type_only) for edge in edges}
    assert observed == {
        ("execution", True),
        ("ports", False),
        ("strategy", False),
    }
    assert all(edge.source_package == "architecture" for edge in edges)
    assert all(edge.source_path == "synthetic.py" for edge in edges)
