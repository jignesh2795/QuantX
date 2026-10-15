"""Structural T8 check for the explicit strategy-context seam set."""
from __future__ import annotations

import ast
from pathlib import Path

_SEAM_FILES = (
    "src/quantx/strategy/context.py",
    "src/quantx/strategy/engine_snapshot.py",
    "src/quantx/strategy/typed_params.py",
    "src/quantx/strategy/runtime.py",
    "src/quantx/strategy/evaluation.py",
    "src/quantx/strategy/deployment.py",
    "src/quantx/application/strategy_preflight.py",
)
_FORBIDDEN_CALLS = {
    "submit_order",
    "place_order",
    "submit_live_order",
    "broker_submit",
    "sleep",
    "call_later",
    "create_task",
}


def test_strategy_seams_have_no_broker_submit_or_scheduler_path() -> None:
    root = Path(__file__).resolve().parents[3]
    observed: list[str] = []
    for relative_path in _SEAM_FILES:
        source = (root / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Name) and function.id in _FORBIDDEN_CALLS:
                    observed.append(f"{relative_path}:{function.id}")
                elif isinstance(function, ast.Attribute) and function.attr in _FORBIDDEN_CALLS:
                    observed.append(f"{relative_path}:{function.attr}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("dhanhq", "ccxt", "ib_insync")):
                        observed.append(f"{relative_path}:import {alias.name}")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(("dhanhq", "ccxt", "ib_insync")):
                    observed.append(f"{relative_path}:import {module}")
    assert observed == []
