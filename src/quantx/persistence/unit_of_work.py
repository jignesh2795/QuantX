"""Compatibility re-exports of the execution-owned persistence contracts.

The protocols live in :mod:`quantx.execution.persistence` — the execution-owned
contract layer that execution and application code depend on. This module
preserves the established ``quantx.persistence`` import path for application
composition and existing consumers; the objects are the same objects, not a
second definition.

Import direction: ``quantx.persistence`` (the implementing side) depends on
``quantx.execution``. The reverse direction remains forbidden, so this
compatibility path cannot be satisfied by execution importing persistence
infrastructure.
"""

from __future__ import annotations

from quantx.execution.persistence import (
    PersistentIdempotencyStore,
    ReceiptRepository,
    UnitOfWork,
)

__all__ = [
    "PersistentIdempotencyStore",
    "ReceiptRepository",
    "UnitOfWork",
]
