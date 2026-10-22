"""Execution-layer dependency boundary tests.

The execution layer owns normalized execution semantics and safety boundaries.
It must depend on the domain and the neutral ``quantx.ports`` contracts, never
on persistence infrastructure. The persistence protocols it consumes are
execution-owned (``quantx.execution.persistence``) and are implemented by
``quantx.persistence``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import quantx.execution


def _execution_source_root() -> Path:
    return Path(quantx.execution.__file__).resolve().parent


def test_execution_package_never_imports_persistence_infrastructure() -> None:
    """No execution module may import ``quantx.persistence`` — not even for types.

    Receipt/idempotency contracts are consumed from ``quantx.execution.persistence``;
    persistence is the implementing side of that boundary. Reintroducing an
    ``execution -> persistence`` import direction recreates the bidirectional
    package dependency (execution ↔ persistence) fixed by this boundary.
    """
    root = _execution_source_root()
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            if "quantx.persistence" in stripped:
                offenders.append(f"{path.relative_to(root)}:{line_number}: {stripped}")
    assert offenders == [], "execution must not import persistence infrastructure"


def test_persistence_contracts_are_owned_by_the_execution_layer() -> None:
    """The canonical protocol definitions live in ``quantx.execution.persistence``."""
    from quantx.execution import persistence as execution_persistence
    from quantx.execution.persistence import ReceiptRepository
    from quantx.persistence import ReceiptRepository as PublicReceiptRepository

    assert ReceiptRepository is execution_persistence.ReceiptRepository
    assert ReceiptRepository.__module__ == "quantx.execution.persistence"
    assert "ReceiptRepository" in execution_persistence.__all__
    assert PublicReceiptRepository is ReceiptRepository


def test_no_ports_persistence_contract_module_remains() -> None:
    """A ``quantx.ports.persistence`` shim would recreate the removed cycle."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("quantx.ports.persistence")


def test_persistence_package_reexports_protocols_for_compatibility() -> None:
    """The documented ``quantx.persistence`` import path keeps resolving."""
    import quantx.persistence
    from quantx.execution.persistence import (
        PersistentIdempotencyStore,
        ReceiptRepository,
        UnitOfWork,
    )

    assert quantx.persistence.PersistentIdempotencyStore is PersistentIdempotencyStore
    assert quantx.persistence.ReceiptRepository is ReceiptRepository
    assert quantx.persistence.UnitOfWork is UnitOfWork
    for name in ("PersistentIdempotencyStore", "ReceiptRepository", "UnitOfWork"):
        assert name in quantx.persistence.__all__
