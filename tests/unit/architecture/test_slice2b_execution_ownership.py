"""QX-07 Slice 2B acceptance: execution-owned receipt and persistence contracts.

These tests encode the ownership decision recorded in the QX-07 Slice 2B
ownership audit (Option B): canonical receipt/outcome/idempotency/quarantine
records stay execution-owned, the receipt-bearing broker port moves into
execution, execution-specific persistence protocols move into an
execution-owned module, and ``quantx.ports`` depends on ``domain`` only.

They are deliberately independent of the guardrail tests they supersede:
after Slice 2B no ``ports -> execution`` edge of any kind may exist, in
runtime or ``TYPE_CHECKING`` analysis, and no known-cycle registry entry may
remain.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from tests.unit.architecture._import_graph import build_import_graph, find_package_cycles

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PORTS_PERSISTENCE_PATH = _REPO_ROOT / "src" / "quantx" / "ports" / "persistence.py"


def _describe(cycles: tuple[tuple[str, ...], ...]) -> str:
    return "\n".join(" -> ".join((*cycle, cycle[0])) for cycle in cycles)


def test_ports_package_has_no_execution_dependency_in_any_import_kind() -> None:
    graph = build_import_graph()
    offenders = [
        edge.describe()
        for edge in graph.edges
        if edge.source_package == "ports" and edge.target_package == "execution"
    ]
    assert offenders == [], "ports must not depend on execution:\n" + "\n".join(offenders)


def test_all_edge_package_graph_is_cycle_free() -> None:
    graph = build_import_graph()
    cycles = find_package_cycles(
        graph.package_pairs(type_only=False) | graph.package_pairs(type_only=True)
    )
    assert cycles == (), "all-edge package cycle remains:\n" + _describe(cycles)


def test_all_edge_cross_package_module_graph_is_cycle_free() -> None:
    graph = build_import_graph()
    cycles = find_package_cycles({(edge.source_module, edge.target_module) for edge in graph.edges})
    assert cycles == (), "all-edge cross-package module cycle remains:\n" + _describe(cycles)


def test_ports_persistence_contract_module_is_removed() -> None:
    assert not _PORTS_PERSISTENCE_PATH.exists(), (
        "quantx.ports.persistence must not remain as a shim; importing execution "
        "from ports would recreate the removed cycle"
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("quantx.ports.persistence")


def test_broker_port_is_canonical_in_execution() -> None:
    from quantx.execution.ports import BrokerPort

    assert BrokerPort.__module__ == "quantx.execution.ports"

    import quantx.ports.broker as neutral_broker

    assert not hasattr(neutral_broker, "BrokerPort")
    assert "BrokerPort" not in neutral_broker.__all__
    assert not hasattr(neutral_broker, "ExecutionReceipt")


def test_neutral_broker_capability_contracts_stay_ports_owned() -> None:
    import quantx.integrations.brokers as legacy
    import quantx.ports.broker as canonical

    for name in (
        "BrokerAdapter",
        "BrokerCapability",
        "BrokerConnectionRef",
        "BrokerDescriptor",
        "CapabilitySet",
    ):
        contract = getattr(canonical, name)
        assert contract.__module__ == "quantx.ports.broker"
        assert name in canonical.__all__
        assert getattr(legacy, name) is contract
        assert not hasattr(legacy, "BrokerPort")


def test_persistence_protocols_are_canonical_in_execution() -> None:
    from quantx.execution import persistence as execution_persistence

    for name in (
        "PersistentIdempotencyStore",
        "QuarantineEvidenceReader",
        "ReceiptRepository",
        "SubmissionQuarantineRepository",
        "UnitOfWork",
    ):
        protocol = getattr(execution_persistence, name)
        assert protocol.__module__ == "quantx.execution.persistence"
        assert name in execution_persistence.__all__


def test_operator_resolution_action_is_owned_by_the_idempotency_records() -> None:
    from quantx.execution.idempotency import OperatorResolutionAction as package_action
    from quantx.execution.idempotency.store import OperatorResolutionAction as store_action

    assert package_action is store_action
    assert store_action.__module__ == "quantx.execution.idempotency.store"
    assert {member.name: member.value for member in store_action} == {
        "CLOSE_UNRESOLVED": "CLOSE_UNRESOLVED"
    }
    assert store_action("CLOSE_UNRESOLVED") is store_action.CLOSE_UNRESOLVED


def test_public_compatibility_paths_preserve_object_identity() -> None:
    import quantx.persistence as public_persistence
    from quantx.execution.persistence import (
        PersistentIdempotencyStore,
        ReceiptRepository,
        UnitOfWork,
    )

    assert public_persistence.PersistentIdempotencyStore is PersistentIdempotencyStore
    assert public_persistence.ReceiptRepository is ReceiptRepository
    assert public_persistence.UnitOfWork is UnitOfWork
    for name in ("PersistentIdempotencyStore", "ReceiptRepository", "UnitOfWork"):
        assert name in public_persistence.__all__


def test_canonical_execution_records_are_not_relocated_or_duplicated() -> None:
    from quantx.execution.ports import ExecutionReceipt as ported_receipt
    from quantx.execution.receipts.models import (
        ExecutionEvidenceKind,
        ExecutionOutcome,
        ExecutionReceipt,
    )
    from quantx.execution.receipts.quarantine import QuarantinedSubmissionObservation

    assert ExecutionReceipt.__module__ == "quantx.execution.receipts.models"
    assert ExecutionOutcome.__module__ == "quantx.execution.receipts.models"
    assert ExecutionEvidenceKind.__module__ == "quantx.execution.receipts.models"
    assert QuarantinedSubmissionObservation.__module__ == "quantx.execution.receipts.quarantine"
    assert ported_receipt is ExecutionReceipt


def test_import_boundary_guardrails_carry_no_stale_cycle_registration() -> None:
    from tests.unit.architecture import test_import_boundaries as boundaries

    assert boundaries._KNOWN_ALL_EDGE_PACKAGE_CYCLES == ()
    assert boundaries._KNOWN_ALL_EDGE_MODULE_CYCLES == ()
    assert boundaries._DEFERRED_TYPE_ONLY == {}
    assert boundaries._DEFERRED_RUNTIME == {}
