"""Execution-layer dependency boundary tests.

The execution layer owns normalized execution semantics and safety boundaries.
It must depend on stable contracts (``quantx.ports``) and the domain, never on
persistence infrastructure: the repository protocols it consumes live in
``quantx.ports.persistence`` and are implemented by ``quantx.persistence``.
"""

from __future__ import annotations

from pathlib import Path

import quantx.execution


def _execution_source_root() -> Path:
    return Path(quantx.execution.__file__).resolve().parent


def test_execution_package_never_imports_persistence_infrastructure() -> None:
    """No execution module may import ``quantx.persistence`` — not even for types.

    Receipt/idempotency contracts are consumed from ``quantx.ports.persistence``;
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
            if stripped.startswith("#"):
                continue
            if (
                "quantx.persistence" in stripped
                and ("import" in stripped or "from" in stripped)
                and "quantx.ports.persistence" not in stripped
            ):
                offenders.append(f"{path.relative_to(root)}:{line_number}: {stripped}")
    assert offenders == [], "execution must not import persistence infrastructure"


def test_persistence_contracts_are_owned_by_the_ports_layer() -> None:
    """The canonical protocol definitions live in ``quantx.ports.persistence``."""
    from quantx.persistence import ReceiptRepository
    from quantx.ports import persistence as port_module
    from quantx.ports.persistence import ReceiptRepository as PortReceiptRepository

    assert ReceiptRepository is PortReceiptRepository
    assert port_module.ReceiptRepository is PortReceiptRepository
    assert "ReceiptRepository" in port_module.__all__


def test_persistence_package_reexports_protocols_for_compatibility() -> None:
    """The documented ``quantx.persistence`` import path keeps resolving."""
    import quantx.persistence
    from quantx.ports.persistence import (
        PersistentIdempotencyStore,
        ReceiptRepository,
        UnitOfWork,
    )

    assert quantx.persistence.PersistentIdempotencyStore is PersistentIdempotencyStore
    assert quantx.persistence.ReceiptRepository is ReceiptRepository
    assert quantx.persistence.UnitOfWork is UnitOfWork
    for name in ("PersistentIdempotencyStore", "ReceiptRepository", "UnitOfWork"):
        assert name in quantx.persistence.__all__
