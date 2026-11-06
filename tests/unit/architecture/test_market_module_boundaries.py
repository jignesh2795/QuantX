"""Nested market-module boundary regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.architecture._import_graph import _resolve_from_base

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPO_ROOT / "src" / "quantx"


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(("quantx", *parts))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source_module = _module_name(path)
    is_package = path.name == "__init__.py"
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_base(
                source_module,
                node.module or "",
                is_package=is_package,
                level=node.level,
            )
            if base is not None:
                targets.add(base)
    return targets


def _python_files(package: str) -> list[Path]:
    return sorted((SOURCE_ROOT / package).rglob("*.py"))


def test_markets_common_imports_only_domain() -> None:
    offenders: list[str] = []
    for path in _python_files("markets/common"):
        for target in _imports(path):
            if target == "quantx.domain" or target.startswith("quantx.domain."):
                continue
            if target.startswith("quantx.markets.common"):
                continue
            if target.startswith("quantx."):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert offenders == [], "\n".join(offenders)


def test_markets_registry_has_no_market_specific_imports() -> None:
    offenders: list[str] = []
    for path in _python_files("markets"):
        if path.name != "registry.py":
            continue
        for target in _imports(path):
            if target.startswith("quantx.markets.india") or target.startswith(
                "quantx.markets.digital_assets"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert offenders == [], "\n".join(offenders)


def test_markets_india_dependencies_are_allowed() -> None:
    allowed_prefixes = (
        "quantx.domain",
        "quantx.markets.common",
        "quantx.markets.india",
        "quantx.ports",
    )
    offenders: list[str] = []
    for path in _python_files("markets/india"):
        for target in _imports(path):
            if not target.startswith("quantx."):
                continue
            if target.startswith(allowed_prefixes):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert offenders == [], "\n".join(offenders)


def test_digital_assets_is_minimal() -> None:
    path = SOURCE_ROOT / "markets" / "digital_assets" / "__init__.py"
    source = path.read_text(encoding="utf-8")
    assert "MARKET_IMPLEMENTED = False" in source
    assert "digital_assets_market_module" in source
    assert "quantx." not in source


def test_ports_has_no_static_or_dynamic_markets_dependency() -> None:
    offenders: list[str] = []
    for path in _python_files("ports"):
        source = path.read_text(encoding="utf-8")
        for target in _imports(path):
            if target == "quantx.markets" or target.startswith("quantx.markets."):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
        if "quantx.markets" in source and "importlib.import_module" in source:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: dynamic markets import")
    assert offenders == [], "\n".join(offenders)


def test_research_market_imports_are_narrow() -> None:
    offenders: list[str] = []
    for path in _python_files("research"):
        for target in _imports(path):
            if target.startswith("quantx.markets.india") or target.startswith(
                "quantx.markets.digital_assets"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert offenders == [], "\n".join(offenders)


def test_markets_does_not_import_research() -> None:
    offenders: list[str] = []
    for path in _python_files("markets"):
        for target in _imports(path):
            if target == "quantx.research" or target.startswith("quantx.research."):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {target}")
    assert offenders == [], "\n".join(offenders)
