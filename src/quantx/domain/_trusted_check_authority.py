"""Private domain-owned authority for trusted market-check identities.

This module has no application, ports, or market imports. The opaque
registrar and exact approved class-object map are shared only by the
markets composition bootstrap and the ports contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

_CORE_REGISTRAR = object()

_APPROVED_METADATA: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "india.session-calendar": (
            "quantx.markets.india.market_checks",
            "IndiaSessionCheck",
        ),
        "india.compatibility-rules": (
            "quantx.markets.india.market_checks",
            "IndiaCompatCheck",
        ),
    }
)

_APPROVED_IMPLEMENTATIONS: dict[str, type] = {}


def _is_core_trusted_check_registrar(candidate: object) -> bool:
    """Check the opaque core registrar by object identity."""
    return candidate is _CORE_REGISTRAR


def _is_approved_trusted_check_implementation(
    check_id: object, implementation: object
) -> bool:
    """Return whether the exact class object was approved by core bootstrap."""
    return (
        isinstance(check_id, str)
        and _APPROVED_IMPLEMENTATIONS.get(check_id) is implementation
    )


def _approve_trusted_check_implementations(
    implementations: Mapping[str, object], registrar: object
) -> None:
    """Approve the complete canonical implementation set, once and idempotently."""
    if not _is_core_trusted_check_registrar(registrar):
        raise PermissionError("invalid trusted-check registrar")
    if set(implementations) != set(_APPROVED_METADATA):
        raise ValueError(
            "trusted-check bootstrap must provide the complete approved set"
        )

    pending: dict[str, type] = {}
    for check_id, expected in _APPROVED_METADATA.items():
        implementation = implementations[check_id]
        if not isinstance(implementation, type):
            raise ValueError("approved trusted-check implementation is unavailable")
        # Metadata is a secondary integrity check. Trust is subsequently
        # determined by identity against this captured class object.
        if (
            implementation.__module__ != expected[0]
            or implementation.__qualname__ != expected[1]
        ):
            raise ValueError("trusted-check implementation metadata is inconsistent")
        existing = _APPROVED_IMPLEMENTATIONS.get(check_id)
        if existing is not None and existing is not implementation:
            raise ValueError("conflicting core-approved trusted implementation")
        pending[check_id] = implementation

    _APPROVED_IMPLEMENTATIONS.update(pending)


__all__: tuple[str, ...] = ()
