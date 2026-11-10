"""Contract tests for the curated public Python API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import quantx.api as api
from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId, Money

_EXPECTED_PUBLIC_IMPORTS = [
    "AssetClass",
    "Contract",
    "Instrument",
    "InstrumentId",
    "MarketContext",
    "MarketFamily",
    "MarketRegion",
    "Money",
    "OptionType",
]


def test_public_api_exports_match_documented_snapshot() -> None:
    assert api.__all__ == _EXPECTED_PUBLIC_IMPORTS
    assert set(api.__api_stability__) == set(_EXPECTED_PUBLIC_IMPORTS)
    assert set(api.__api_stability__.values()) == {"provisional"}


def test_public_api_reexports_canonical_contract_identities() -> None:
    assert api.AssetClass is AssetClass
    assert api.Contract is Contract
    assert api.Instrument is Instrument
    assert api.InstrumentId is InstrumentId
    assert api.MarketContext is MarketContext
    assert api.MarketFamily is MarketFamily
    assert api.MarketRegion is MarketRegion
    assert api.Money is Money
    assert api.OptionType is OptionType


def test_api_stability_manifest_is_immutable() -> None:
    with pytest.raises(TypeError):
        api.__api_stability__["Money"] = "stable"  # type: ignore[index]


def test_public_api_import_needs_no_sdk_or_network() -> None:
    script = """
import socket
import sys

def reject_network(*args, **kwargs):
    raise AssertionError("quantx.api import attempted network access")

socket.getaddrinfo = reject_network
socket.create_connection = reject_network
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network

import quantx.api

assert "dhanhq" not in sys.modules
assert not any(
    name == "quantx.plugins.dhan" or name.startswith("quantx.plugins.dhan.")
    for name in sys.modules
)
assert not any(
    name == "quantx.application" or name.startswith("quantx.application.")
    for name in sys.modules
)
"""
    repository_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
