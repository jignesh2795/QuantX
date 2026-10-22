"""Ownership and compatibility regressions for persistence-port contracts."""

from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import quantx.persistence
import quantx.ports.persistence as persistence_port
from quantx.execution.idempotency import (
    OperatorResolution,
    PendingExecutionContext,
    PendingExecutionRecoveryRecord,
)
from quantx.execution.idempotency import (
    OperatorResolutionAction as ExecutionOperatorResolutionAction,
)
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.quarantine import QuarantinedSubmissionObservation
from quantx.persistence.sqlite import SqliteDatabase, SqliteIdempotencyStore
from quantx.ports.persistence import (
    OperatorResolutionAction as PortOperatorResolutionAction,
)
from quantx.ports.persistence import (
    PersistentIdempotencyStore,
    QuarantineEvidenceReader,
    ReceiptRepository,
    SubmissionQuarantineRepository,
    UnitOfWork,
)


def test_port_and_legacy_execution_paths_expose_the_same_action_enum() -> None:
    assert PortOperatorResolutionAction is ExecutionOperatorResolutionAction
    assert (
        PortOperatorResolutionAction.CLOSE_UNRESOLVED
        is ExecutionOperatorResolutionAction.CLOSE_UNRESOLVED
    )
    assert PortOperatorResolutionAction.__module__ == "quantx.ports.persistence"
    assert PortOperatorResolutionAction.CLOSE_UNRESOLVED.value == "CLOSE_UNRESOLVED"


def test_operator_action_values_are_wire_stable() -> None:
    assert {member.name: member.value for member in PortOperatorResolutionAction} == {
        "CLOSE_UNRESOLVED": "CLOSE_UNRESOLVED"
    }
    assert (
        PortOperatorResolutionAction("CLOSE_UNRESOLVED")
        is PortOperatorResolutionAction.CLOSE_UNRESOLVED
    )


def test_closed_unresolved_default_is_preserved_at_every_boundary() -> None:
    from quantx.application.operator_resolution import resolve_pending_operator

    assert (
        inspect.signature(resolve_pending_operator).parameters["action"].default
        is PortOperatorResolutionAction.CLOSE_UNRESOLVED
    )
    assert (
        inspect.signature(PersistentIdempotencyStore.resolve_operator).parameters["action"].default
        is PortOperatorResolutionAction.CLOSE_UNRESOLVED
    )
    assert (
        inspect.signature(SqliteIdempotencyStore.resolve_operator).parameters["action"].default
        is PortOperatorResolutionAction.CLOSE_UNRESOLVED
    )


def test_persisted_operator_action_value_is_unchanged(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()
    fingerprint = "a" * 64

    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, fingerprint)
        store.resolve_operator(
            client_order_id,
            fingerprint,
            operator_id="operator-1",
            reason="unresolvable pending order",
            resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT action FROM operator_resolutions WHERE client_order_id = ?",
            (str(client_order_id),),
        ).fetchone()

    assert row == ("CLOSE_UNRESOLVED",)


def test_persistence_protocols_remain_owned_by_the_ports_layer() -> None:
    for name in (
        "PersistentIdempotencyStore",
        "QuarantineEvidenceReader",
        "ReceiptRepository",
        "SubmissionQuarantineRepository",
        "UnitOfWork",
    ):
        protocol = getattr(persistence_port, name)
        assert protocol.__module__ == "quantx.ports.persistence"
        assert name in persistence_port.__all__

    assert quantx.persistence.PersistentIdempotencyStore is PersistentIdempotencyStore
    assert quantx.persistence.ReceiptRepository is ReceiptRepository
    assert quantx.persistence.UnitOfWork is UnitOfWork
    assert QuarantineEvidenceReader is persistence_port.QuarantineEvidenceReader
    assert SubmissionQuarantineRepository is persistence_port.SubmissionQuarantineRepository


def test_canonical_execution_records_were_not_duplicated_or_relocated() -> None:
    assert ExecutionReceipt.__module__ == "quantx.execution.receipts.models"
    assert ExecutionOutcome.__module__ == "quantx.execution.receipts.models"
    assert OperatorResolution.__module__ == "quantx.execution.idempotency.store"
    assert PendingExecutionContext.__module__ == "quantx.execution.idempotency.store"
    assert PendingExecutionRecoveryRecord.__module__ == "quantx.execution.idempotency.store"
    assert QuarantinedSubmissionObservation.__module__ == "quantx.execution.receipts.quarantine"
