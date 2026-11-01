"""Core-owned composition for canonical trusted market-check identities.

Market-specific implementation resolution belongs in the markets package,
not in application source. This module captures the canonical India class
objects once and pins only those exact objects through the core-issued
registrar capability.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from quantx.domain._trusted_check_authority import (
    _CORE_REGISTRAR as _REGISTRAR,
    _approve_trusted_check_implementations,
)
from quantx.markets.india.market_checks import IndiaCompatCheck, IndiaSessionCheck
from quantx.ports.market_checks import _register_trusted_check


# Resolve the canonical implementation path, never the legacy quantx.india
# compatibility shim. Capture class objects once so later module rebinding
# cannot replace the approved identities.
_APPROVED_INDIA_CHECKS: Mapping[str, type] = MappingProxyType(
    {
        "india.session-calendar": IndiaSessionCheck,
        "india.compatibility-rules": IndiaCompatCheck,
    }
)
_approve_trusted_check_implementations(_APPROVED_INDIA_CHECKS, _REGISTRAR)


def _make_registration_bootstrap(registrar: object) -> Callable[[], None]:
    """Keep the registrar in a closure instead of the module namespace."""

    def ensure() -> None:
        for check_id, implementation in _APPROVED_INDIA_CHECKS.items():
            _register_trusted_check(check_id, implementation, registrar)

    return ensure


ensure_india_trusted_checks_registered = _make_registration_bootstrap(_REGISTRAR)
del _REGISTRAR
del _make_registration_bootstrap


__all__ = ["ensure_india_trusted_checks_registered"]
