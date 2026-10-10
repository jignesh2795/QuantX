"""Compatibility re-exports of the database-neutral persistence contracts.

The protocols live in :mod:`quantx.ports.persistence` — the stable-contract
layer that execution and application code depend on. This module preserves the
established ``quantx.persistence`` import path for application composition and
existing consumers; new execution-layer code must import the contracts from
``quantx.ports.persistence`` instead of depending on persistence infrastructure.
"""

from __future__ import annotations

from quantx.ports.persistence import (
    PersistentIdempotencyStore,
    ReceiptRepository,
    UnitOfWork,
)

__all__ = [
    "PersistentIdempotencyStore",
    "ReceiptRepository",
    "UnitOfWork",
]
