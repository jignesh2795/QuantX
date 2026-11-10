"""Contract tests for QuantX's curated public Python API."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from quantx import api
from quantx.domain.clock import Clock, SimulatedClock, SystemClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, PositionEffect, TimeInForce
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.market_data import Candle, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.value_objects import (
    AccountId,
    BrokerConnectionId,
    InstrumentId,
    Money,
    ProductCode,
)
from quantx.ports.market_data import MarketDataPort, MarketDataStore

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
    "Money",
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
    assert set(api.__api_stability__) == set(EXPECTED_PUBLIC_API)
    assert set(api.__api_stability__.values()) == {"provisional"}
    assert all(getattr(api, name, None) is not None for name in EXPECTED_PUBLIC_API)


def test_public_api_reexports_canonical_contract_identities() -> None:
    expected = {
        "AccountId": AccountId,
        "AssetClass": AssetClass,
        "BrokerConnectionId": BrokerConnectionId,
        "Candle": Candle,
        "Clock": Clock,
        "Contract": Contract,
        "ExecutionContext": ExecutionContext,
        "ExecutionMode": ExecutionMode,
        "Instrument": Instrument,
        "InstrumentId": InstrumentId,
        "MarketContext": MarketContext,
        "MarketDataPort": MarketDataPort,
        "MarketDataStore": MarketDataStore,
        "MarketFamily": MarketFamily,
        "MarketRegion": MarketRegion,
        "Money": Money,
        "OptionType": OptionType,
        "OrderSide": OrderSide,
        "OrderType": OrderType,
        "PortfolioId": PortfolioId,
        "PositionEffect": PositionEffect,
        "ProductCode": ProductCode,
        "Quote": Quote,
        "SimulatedClock": SimulatedClock,
        "StrategyDeploymentId": StrategyDeploymentId,
        "SystemClock": SystemClock,
        "TimeInForce": TimeInForce,
        "TradeIntent": TradeIntent,
    }
    assert all(getattr(api, name) is canonical for name, canonical in expected.items())


def test_api_stability_manifest_is_immutable() -> None:
    with pytest.raises(TypeError):
        api.__api_stability__["Money"] = "stable"  # type: ignore[index]


def test_public_money_contract_keeps_decimal_and_currency_guards() -> None:
    with pytest.raises(TypeError, match="amount must be a Decimal"):
        Money(1.0, "INR")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="amount must be finite"):
        Money(Decimal("NaN"), "INR")
    with pytest.raises(ValueError, match="currency mismatch"):
        Money(Decimal("1"), "INR") + Money(Decimal("1"), "USD")


def test_public_api_imports_only_domain_and_market_data_port_contracts() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    api_path = repository_root / "src" / "quantx" / "api.py"
    tree = ast.parse(api_path.read_text(encoding="utf-8"))
    quantx_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("quantx.")
    }
    assert quantx_imports
    assert all(
        module.startswith("quantx.domain.") or module == "quantx.ports.market_data"
        for module in quantx_imports
    )


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
socket.getaddrinfo = reject_network
socket.socket = reject_network

import quantx.api

assert "dhanhq" not in sys.modules
assert not any(
    name == "quantx.application" or name.startswith("quantx.application.")
    for name in sys.modules
)
assert not any(
    name == "quantx.plugins" or name.startswith("quantx.plugins.")
    for name in sys.modules
)
assert not any(
    name == "quantx.integrations" or name.startswith("quantx.integrations.")
    for name in sys.modules
)
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
