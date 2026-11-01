"""Composition helpers for market-owned trusted checks."""

from __future__ import annotations

import importlib

from quantx.ports.market_checks import (
    bootstrap_trusted_checks,
    register_trusted_check,
    register_trusted_check_bootstrap,
)


def _resolve_canonical(name: str) -> type:
    module = importlib.import_module("quantx.markets.india.market_checks")
    value = getattr(module, name)
    if not isinstance(value, type):
        raise TypeError(f"{name} is not a class")
    return value


_APPROVED_INDIA_SESSION_CHECK = _resolve_canonical("IndiaSessionCheck")
_APPROVED_INDIA_COMPAT_CHECK = _resolve_canonical("IndiaCompatCheck")


def _bootstrap(registrar: object) -> None:
    register_trusted_check("india.session-calendar", _APPROVED_INDIA_SESSION_CHECK, registrar)
    register_trusted_check("india.compatibility-rules", _APPROVED_INDIA_COMPAT_CHECK, registrar)


register_trusted_check_bootstrap(_bootstrap)


def ensure_india_trusted_checks_registered() -> None:
    """Run the core-controlled trusted-check bootstrap."""
    bootstrap_trusted_checks()


__all__ = ["ensure_india_trusted_checks_registered"]
