"""Static guard for the reviewed system-wall-clock boundaries in QuantX."""

from __future__ import annotations

import ast
from pathlib import Path

# Counts are exact AST call-expression counts, not grep hits. Each retained
# path is intentional: SystemClock implementation, interactive object
# defaults, broker observation fallbacks, persistence audit stamps, or
# separately audited operator activity. New or displaced wall-clock reads
# require review and an explicit allowlist change.
ALLOWED_WALL_CLOCK_CALLS: dict[str, int] = {
    "application/execution.py": 3,
    "application/operator_resolution.py": 1,
    "domain/clock.py": 1,
    "domain/orders.py": 1,
    "domain/strategy.py": 1,
    "persistence/sqlite/idempotency.py": 5,
    "persistence/sqlite/research.py": 1,
    "persistence/sqlite/schema.py": 8,
    "persistence/sqlite/trading_gate.py": 1,
    "plugins/dhan/adapter.py": 2,
    "plugins/dhan/transport.py": 28,
    "research/experiments.py": 1,
}

_TIME_METHODS = {
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "perf_counter_ns",
    "process_time",
    "process_time_ns",
    "thread_time",
    "thread_time_ns",
    "clock_gettime",
    "clock_gettime_ns",
    "localtime",
    "gmtime",
    "ctime",
    "asctime",
}


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return None if prefix is None else f"{prefix}.{node.attr}"
    return None


def _wall_clock_calls(tree: ast.Module) -> int:
    datetime_modules = {"datetime"}
    time_modules = {"time"}
    datetime_types = {"datetime"}
    date_types = {"date"}
    time_functions: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "datetime":
                    datetime_modules.add(imported.asname or "datetime")
                elif imported.name == "time":
                    time_modules.add(imported.asname or "time")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "datetime":
                for imported in node.names:
                    if imported.name == "datetime":
                        datetime_types.add(imported.asname or imported.name)
                    elif imported.name == "date":
                        date_types.add(imported.asname or imported.name)
            elif node.module == "time":
                for imported in node.names:
                    if imported.name in _TIME_METHODS:
                        time_functions.add(imported.asname or imported.name)

    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in time_functions:
            count += 1
            continue
        if not isinstance(function, ast.Attribute):
            continue
        owner = _dotted_name(function.value)
        method = function.attr
        datetime_owners = datetime_types | {
            f"{module}.datetime" for module in datetime_modules
        }
        date_owners = date_types | {
            f"{module}.date" for module in datetime_modules
        }
        if (method in {"now", "utcnow"} and owner in datetime_owners) or (
            method == "today" and owner in date_owners
        ):
            count += 1
        elif owner in time_modules and method in _TIME_METHODS:
            count += 1
    return count


def test_direct_wall_clock_calls_match_the_reviewed_allowlist() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "src" / "quantx"
    actual: dict[str, int] = {}
    for path in sorted(source_root.rglob("*.py")):
        count = _wall_clock_calls(ast.parse(path.read_text(encoding="utf-8")))
        if count:
            actual[path.relative_to(source_root).as_posix()] = count

    assert actual == ALLOWED_WALL_CLOCK_CALLS