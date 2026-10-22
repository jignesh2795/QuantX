"""Deterministic AST import-graph helpers for package-boundary tests.

The graph intentionally collapses ``quantx.<package>`` modules and submodules
into top-level package edges. ``file:line`` locations remain attached so a
violation can be inspected directly.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPO_ROOT / "src" / "quantx"
_PACKAGE_PREFIX = "quantx."


@dataclass(frozen=True, slots=True, order=True)
class ImportEdge:
    source_module: str
    source_path: str
    lineno: int
    target_module: str
    target_package: str
    type_only: bool

    @property
    def source_package(self) -> str:
        package = _package_of(self.source_module)
        assert package is not None
        return package

    def describe(self) -> str:
        kind = "type-checking" if self.type_only else "runtime"
        return (
            f"{self.source_path}:{self.lineno}: {kind} import "
            f"{self.source_package} -> {self.target_package} ({self.target_module})"
        )


@dataclass(frozen=True, slots=True)
class ImportGraph:
    edges: tuple[ImportEdge, ...]
    module_count: int

    def by_kind(self, *, type_only: bool) -> tuple[ImportEdge, ...]:
        return tuple(edge for edge in self.edges if edge.type_only is type_only)

    def package_pairs(self, *, type_only: bool) -> frozenset[tuple[str, str]]:
        return frozenset(
            (edge.source_package, edge.target_package) for edge in self.by_kind(type_only=type_only)
        )


def _package_of(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "quantx":
        return None
    return parts[1]


def _module_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(("quantx", *parts))


def _is_type_checking_test(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _resolve_from_base(
    source_module: str,
    target_module: str,
    *,
    is_package: bool,
    level: int,
) -> str | None:
    if level == 0:
        return target_module or None
    parts = source_module.split(".")
    package_parts = list(parts) if is_package else parts[:-1]
    climb = level - 1
    if climb >= len(package_parts) + 1:
        return None
    base_parts = package_parts[: len(package_parts) - climb]
    if not base_parts:
        return None
    base = ".".join(base_parts)
    return f"{base}.{target_module}" if target_module else base


class _ImportVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        module: str,
        source_path: str,
        is_package: bool,
        known_modules: frozenset[str],
        edges: set[ImportEdge],
    ) -> None:
        self._module = module
        self._source_path = source_path
        self._is_package = is_package
        self._known_modules = known_modules
        self._edges = edges
        self._type_only_depth = 0

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_test(node.test):
            self._type_only_depth += 1
            try:
                for child in node.body:
                    self.visit(child)
            finally:
                self._type_only_depth -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = _resolve_from_base(
            self._module,
            node.module or "",
            is_package=self._is_package,
            level=node.level,
        )
        if base is None:
            return
        targets: set[str] = set()
        for alias in node.names:
            if alias.name == "*":
                targets.add(base)
                continue
            candidate = f"{base}.{alias.name}"
            targets.add(candidate if candidate in self._known_modules else base)
        for target in sorted(targets):
            self._add(target, node.lineno)

    def _add(self, target_module: str, lineno: int) -> None:
        if not target_module.startswith(_PACKAGE_PREFIX):
            return
        target_package = _package_of(target_module)
        source_package = _package_of(self._module)
        if target_package is None or source_package is None:
            return
        if target_package == source_package:
            return
        self._edges.add(
            ImportEdge(
                source_module=self._module,
                source_path=self._source_path,
                lineno=lineno,
                target_module=target_module,
                target_package=target_package,
                type_only=self._type_only_depth > 0,
            )
        )


def extract_imports(
    source: str,
    *,
    module: str,
    known_modules: frozenset[str],
    is_package: bool = False,
    source_path: str = "synthetic.py",
) -> tuple[ImportEdge, ...]:
    edges: set[ImportEdge] = set()
    visitor = _ImportVisitor(
        module=module,
        source_path=source_path,
        is_package=is_package,
        known_modules=known_modules,
        edges=edges,
    )
    visitor.visit(ast.parse(source, filename=source_path))
    return tuple(sorted(edges))


def build_import_graph(source_root: Path | None = None) -> ImportGraph:
    root = _SOURCE_ROOT if source_root is None else source_root
    paths = sorted(root.rglob("*.py"))
    known_modules = frozenset(_module_name(path, root) for path in paths)
    edges: set[ImportEdge] = set()
    for path in paths:
        module = _module_name(path, root)
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(_REPO_ROOT).as_posix()
        visitor = _ImportVisitor(
            module=module,
            source_path=relative_path,
            is_package=path.name == "__init__.py",
            known_modules=known_modules,
            edges=edges,
        )
        visitor.visit(ast.parse(source, filename=relative_path))
    return ImportGraph(edges=tuple(sorted(edges)), module_count=len(paths))


def find_package_cycles(
    pairs: Iterable[tuple[str, str]],
) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for source, target in pairs:
        if source == target:
            continue
        adjacency.setdefault(source, set()).add(target)
        nodes.update((source, target))

    found: set[tuple[str, ...]] = set()

    def _walk(start: str, current: str, path: tuple[str, ...]) -> None:
        for neighbour in sorted(adjacency.get(current, ())):
            if neighbour == start:
                cycle = path
                pivot = cycle.index(min(cycle))
                found.add(cycle[pivot:] + cycle[:pivot])
            elif neighbour not in path:
                _walk(start, neighbour, (*path, neighbour))

    for start in sorted(nodes):
        _walk(start, start, (start,))
    return tuple(sorted(found))
