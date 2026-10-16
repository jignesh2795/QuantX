"""Structural T8 check for forbidden LIVE, broker-submit, and scheduler paths."""

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
    "src/quantx/application/backtest.py",
    "src/quantx/application/strategy_rehearsal.py",
)
_FORBIDDEN_CALLS = {
    "submit",
    "submit_order",
    "place_order",
    "send_order",
    "submit_live_order",
    "broker_submit",
    "execute_live_order",
    "create_order",
    "sleep",
    "call_later",
    "call_at",
    "create_task",
    "schedule",
    "schedule_timer",
    "register_timer",
    "cancel_timer",
    "add_job",
    "run_pending",
}
_WALL_CLOCK_BARE_CALLS = {"now", "utcnow", "today", "monotonic"}
_WALL_CLOCK_QUALIFIED_CALLS = {
    "datetime.now",
    "datetime.datetime.now",
    "datetime.utcnow",
    "datetime.datetime.utcnow",
    "date.today",
    "datetime.date.today",
    "time.time",
    "time.monotonic",
    "time.perf_counter",
    "time.process_time",
}
_FORBIDDEN_IMPORT_PREFIXES = (
    "dhanhq",
    "ccxt",
    "ib_insync",
    "kiteconnect",
    "upstox_client",
    "fyers_apiv3",
    "time",
    "asyncio",
    "sched",
    "apscheduler",
    "schedule",
)


def _dotted_name(node: ast.expr) -> str | None:
    """Return a dotted import/name path, excluding arbitrary object attributes."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return None if prefix is None else f"{prefix}.{node.attr}"
    return None


def _audit_source(source: str, relative_path: str) -> list[str]:
    """Return static boundary violations; deliberately not a proof against reflection."""
    tree = ast.parse(source, filename=relative_path)
    observed: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                if function.id in _FORBIDDEN_CALLS | _WALL_CLOCK_BARE_CALLS:
                    observed.append(f"{relative_path}:call {function.id}")
            elif isinstance(function, ast.Attribute):
                dotted = _dotted_name(function)
                if function.attr in _FORBIDDEN_CALLS:
                    observed.append(f"{relative_path}:call {function.attr}")
                elif dotted in _WALL_CLOCK_QUALIFIED_CALLS:
                    observed.append(f"{relative_path}:call {dotted}")
        if isinstance(node, ast.Attribute) and node.attr == "LIVE":
            observed.append(f"{relative_path}:LIVE attribute")
        if isinstance(node, ast.Name) and node.id == "LIVE":
            observed.append(f"{relative_path}:LIVE name")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_FORBIDDEN_IMPORT_PREFIXES):
                    observed.append(f"{relative_path}:import {alias.name}")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(_FORBIDDEN_IMPORT_PREFIXES):
                observed.append(f"{relative_path}:import {module}")
    return observed


def test_strategy_seams_have_no_broker_submit_or_scheduler_path() -> None:
    root = Path(__file__).resolve().parents[3]
    observed: list[str] = []
    for relative_path in _SEAM_FILES:
        source = (root / relative_path).read_text(encoding="utf-8")
        observed.extend(_audit_source(source, relative_path))
    assert observed == []


def test_boundary_scanner_detects_live_submit_wallclock_and_scheduler_sentinels() -> None:
    unsafe_source = """
import asyncio
import datetime
import time

from quantx.domain.deployment import ExecutionMode


def unsafe(broker):
    datetime.datetime.now()
    time.time()
    time.sleep(1)
    asyncio.create_task(None)
    broker.submit(None)
    mode = ExecutionMode.LIVE
"""
    observed = _audit_source(unsafe_source, "sentinel.py")

    assert "sentinel.py:import asyncio" in observed
    assert "sentinel.py:import time" in observed
    assert "sentinel.py:call datetime.datetime.now" in observed
    assert "sentinel.py:call time.time" in observed
    assert _audit_source("engine_clock.now()", "deterministic_clock.py") == []
    assert "sentinel.py:call sleep" in observed
    assert "sentinel.py:call create_task" in observed
    assert "sentinel.py:call submit" in observed
    assert "sentinel.py:LIVE attribute" in observed
