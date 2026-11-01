"""Composition helpers for market-owned trusted checks."""

from __future__ import annotations

import importlib

from quantx.ports.market_checks import _REGISTRAR, register_trusted_check


def ensure_india_trusted_checks_registered() -> None:
    """Register the approved India trusted checks through the core capability."""

    module = importlib.import_module("quantx.markets.india.market_checks")
    register_trusted_check(
        "india.session-calendar",
        module.IndiaSessionCheck,
        _REGISTRAR,
    )
    register_trusted_check(
        "india.compatibility-rules",
        module.IndiaCompatCheck,
        _REGISTRAR,
    )


__all__ = ["ensure_india_trusted_checks_registered"]
