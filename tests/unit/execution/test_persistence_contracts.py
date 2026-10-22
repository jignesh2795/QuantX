"""Ownership and compatibility regressions for execution persistence contracts.

QX-07 Slice 2B moved these protocols out of ``quantx.ports.persistence`` into
``quantx.execution.persistence`` and ``OperatorResolutionAction`` into the
idempotency record module. The assertions below pin the new canonical module
paths, keep the wire values and default boundaries, and keep the public
``quantx.persistence`` compatibility path identity-preserving.
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import quantx.execution.persistence as execution_persistence
import quantx.persistence
from quantx.execution.idempotency import (
    OperatorResolution,
    OperatorResolutionAction,
    PendingExecutionContext,
    PendingExecutionRecoveryRecord,
)
from quantx.execution.idempotency.store import (
    OperatorResolutionAction as StoreOperatorResolutionAction,
)
from quantx.execution.persistence import (
    PersistentIdempotencyStore,
    QuarantineEvidenceReader,
    ReceiptRepository,
    SubmissionQuarantineRepository,
    UnitOfWork,
)
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.quarantine import QuarantinedSubmissionObservation
from quantx.persistence.sqlite import SqliteDatabase, SqliteIdempotencyStore


def test_operator_action_has_one_canonical_definition() -> None:
    assert OperatorResolutionAction is StoreOperatorResolutionAction
    assert OperatorResolutionAction.__module__ == "quantx.execution.idempotency.store"
    assert (
        OperatorResolutionAction.CLOSE_UNRESOLVED is StoreOperatorResolutionAction.CLOSE_UNRESOLVED
    )


def test_operator_action_values_are_wire_stable() -> None:
    assert {member.name: member.value for member in OperatorResolutionAction} == {
        "CLOSE_UNRESOLVED": "CLOSE_UNRESOLVED"
    }
    assert OperatorResolutionAction("CLOSE_UNRESOLVED") is OperatorResolutionAction.CLOSE_UNRESOLVED


def test_closed_unresolved_default_is_preserved_at_every_boundary() -> None:
    from quantx.application.operator_resolution import resolve_pending_operator

    assert (
        inspect.signature(resolve_pending_operator).parameters["action"].default
        is OperatorResolutionAction.CLOSE_UNRESOLVED
    )
    assert (
        inspect.signature(PersistentIdempotencyStore.resolve_operator).parameters["action"].default
        is OperatorResolutionAction.CLOSE_UNRESOLVED
    )
    assert (
        inspect.signature(SqliteIdempotencyStore.resolve_operator).parameters["action"].default
        is OperatorResolutionAction.CLOSE_UNRESOLVED
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


def test_persistence_protocols_are_owned_by_the_execution_layer() -> None:
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

    assert quantx.persistence.PersistentIdempotencyStore is PersistentIdempotencyStore
    assert quantx.persistence.ReceiptRepository is ReceiptRepository
    assert quantx.persistence.UnitOfWork is UnitOfWork
    assert QuarantineEvidenceReader is execution_persistence.QuarantineEvidenceReader
    assert SubmissionQuarantineRepository is execution_persistence.SubmissionQuarantineRepository


def test_canonical_execution_records_were_not_duplicated_or_relocated() -> None:
    assert ExecutionReceipt.__module__ == "quantx.execution.receipts.models"
    assert ExecutionOutcome.__module__ == "quantx.execution.receipts.models"
    assert OperatorResolution.__module__ == "quantx.execution.idempotency.store"
    assert PendingExecutionContext.__module__ == "quantx.execution.idempotency.store"
    assert PendingExecutionRecoveryRecord.__module__ == "quantx.execution.idempotency.store"
    assert QuarantinedSubmissionObservation.__module__ == "quantx.execution.receipts.quarantine"
