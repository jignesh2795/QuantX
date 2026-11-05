"""Contract tests for QuantX's curated public Python API."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from quantx import api


EXPECTED_PUBLIC_API = [
    "AccountId",
    "AssetClass",
    "BrokerConnectionId",
    "Candle",
    "Clock",
    "Contract",
    "ExecutionContext",
    "ExecutionMode",
    "Instrument",
    "InstrumentId",
    "MarketContext",
    "MarketDataPort",
    "MarketDataStore",
    "MarketFamily",
    "MarketRegion",
    "OptionType",
    "OrderSide",
    "OrderType",
    "PortfolioId",
    "PositionEffect",
    "ProductCode",
    "Quote",
    "SimulatedClock",
    "StrategyDeploymentId",
    "SystemClock",
    "TimeInForce",
    "TradeIntent",
]


def test_public_api_exports_match_the_curated_snapshot() -> None:
    assert api.__all__ == EXPECTED_PUBLIC_API
    assert len(api.__all__) == len(set(api.__all__))
    assert all(getattr(api, name, None) is not None for name in EXPECTED_PUBLIC_API)


def test_public_api_import_is_vendor_free_and_network_free() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    source_path = str(repository_root / "src")
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path if not existing_path else os.pathsep.join((source_path, existing_path))
    )
    script = """
import socket
import sys

def reject_network(*args, **kwargs):
    raise AssertionError("quantx.api import attempted network access")

socket.create_connection = reject_network
socket.socket.connect = reject_network

import quantx.api

assert "dhanhq" not in sys.modules
assert not any(
    name == "quantx.application" or name.startswith("quantx.application.")
    for name in sys.modules
)
assert not any(name.startswith("quantx.plugins.dhan") for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
