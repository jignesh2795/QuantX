"""Static guard for reviewed wall-clock boundaries.

Behavioral time must enter application, recovery, reconciliation, and execution
code through an injected ``Clock``. Direct wall-clock calls are permitted only
in the explicitly reviewed operational, transport, audit, and interactive
default modules listed below.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "quantx"
assert _SRC_ROOT.is_dir(), f"QuantX source root not found: {_SRC_ROOT}"


_ALLOWED_PREFIXES = (
    "domain/clock.py",
    "domain/orders.py",
    "domain/strategy.py",
    "research/experiments.py",
    "persistence/sqlite/",
    "plugins/dhan/",
)


def _is_allowed(relative_path: str) -> bool:
    return any(
        relative_path == prefix or relative_path.startswith(prefix) for prefix in _ALLOWED_PREFIXES
    )


def _collect_import_aliases(tree: ast.Module) -> dict[str, tuple[str, str, str]]:
    """Map local names to (import_kind, module, imported_name)."""
    aliases: dict[str, tuple[str, str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                aliases[alias.asname or root] = ("module", alias.name, root)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                aliases[alias.asname or alias.name] = ("from", module, alias.name)
    return aliases


def _resolve_attribute_receiver(
    node: ast.expr, aliases: dict[str, tuple[str, str, str]]
) -> tuple[str, str] | None:
    """Resolve an attribute receiver to (module, imported_or_attribute_name)."""
    if isinstance(node, ast.Name):
        alias = aliases.get(node.id)
        if alias is not None:
            _, module, imported_name = alias
            return module, imported_name
        if node.id in {"datetime", "time"}:
            return node.id, node.id
        return None

    if isinstance(node, ast.Attribute):
        parent = _resolve_attribute_receiver(node.value, aliases)
        if parent is not None:
            module, _parent_name = parent
            return module, node.attr

    return None


def _is_wall_clock_call(
    node: ast.Call, aliases: dict[str, tuple[str, str, str]] | None = None
) -> bool:
    aliases = aliases or {}
    func = node.func

    if isinstance(func, ast.Attribute):
        attr = func.attr
        receiver = _resolve_attribute_receiver(func.value, aliases)
        if receiver is not None:
            module, imported_name = receiver
            if attr in {"now", "utcnow"} and (imported_name == "datetime" or module == "datetime"):
                return True
            if attr in {"time", "monotonic"} and (imported_name == "time" or module == "time"):
                return True

        if isinstance(func.value, ast.Name) and func.value.id in {"datetime", "time"}:
            if func.value.id == "datetime" and attr in {"now", "utcnow"}:
                return True
            if func.value.id == "time" and attr in {"time", "monotonic"}:
                return True

    if isinstance(func, ast.Name):
        alias = aliases.get(func.id)
        if alias is not None:
            _, module, imported_name = alias
            if imported_name in {"utc_now", "utcnow"}:
                return True
            if module == "time" and imported_name in {"time", "monotonic"}:
                return True
        if func.id in {"utc_now", "utcnow"}:
            return True

    return False


def _wall_clock_calls(source: str) -> list[int]:
    tree = ast.parse(source)
    aliases = _collect_import_aliases(tree)
    violations: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_wall_clock_call(node, aliases):
            violations.append(node.lineno)
    return violations


def find_unreviewed_wall_clock_calls(src_root: Path | None = None) -> list[str]:
    root = src_root if src_root is not None else _SRC_ROOT
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if _is_allowed(relative):
            continue
        for lineno in _wall_clock_calls(path.read_text(encoding="utf-8")):
            violations.append(f"{relative}:{lineno}")
    return violations


def test_static_guard_source_root_exists() -> None:
    assert _SRC_ROOT.exists()
    assert _SRC_ROOT.is_dir()


def test_static_guard_detects_forbidden_wall_clock_forms() -> None:
    source = """
import datetime
import datetime as dt
from datetime import datetime as Datetime
import time
import time as clock
from time import time as current_time, monotonic as mono
from quantx.domain.orders import utc_now as wall_now
from datetime import utcnow as utc_now_alias

datetime.datetime.now()
datetime.datetime.utcnow()
dt.datetime.now()
dt.datetime.utcnow()
Datetime.now()
clock.time()
clock.monotonic()
current_time()
mono()
wall_now()
utc_now_alias()
"""
    violations = _wall_clock_calls(source)
    assert len(violations) == 11
    assert violations == list(range(11, 22))


def test_static_guard_rejects_unrelated_attribute_calls() -> None:
    source = """
import datetime as dt
import time as clock

dt.date.today()
clock.sleep(1)
some_object.now()
datetime.timezone.utc
"""
    assert _wall_clock_calls(source) == []


def test_static_guard_allows_reviewed_modules() -> None:
    assert find_unreviewed_wall_clock_calls() == []


def test_direct_wall_clock_calls_are_confined_to_reviewed_modules() -> None:
    violations = find_unreviewed_wall_clock_calls()
    assert not violations, "unreviewed direct wall-clock calls:\n" + "\n".join(violations)
