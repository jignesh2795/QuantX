"""Compatibility shim for broker capability contracts.

The canonical definitions live in :mod:`quantx.ports.broker`. This module keeps
the historical import path working for downstream integrations, plugins, tests,
and application code without maintaining a second definition.
"""

from __future__ import annotations

from quantx.ports.broker import (
    BrokerAdapter,
    BrokerCapability,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)

__all__ = [
    "BrokerAdapter",
    "BrokerCapability",
    "BrokerConnectionRef",
    "BrokerDescriptor",
    "CapabilitySet",
]
