"""SQLite persistence adapters for durable research runs and outputs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from quantx.research.artifacts import ResearchArtifactManifest
from quantx.research.result import ResearchResult
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import (
    ResearchRunRepository,
    research_manifest_from_payload,
    research_provenance_from_payload,
    research_result_from_payload,
    research_result_to_payload,
)

from .database import SqliteDatabase


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _payload(value: str, field_name: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must contain a JSON object")
    return dict(parsed)


def _insert_result(connection: sqlite3.Connection, result: ResearchResult) -> None:
    row = connection.execute(
        "SELECT payload FROM research_results WHERE result_id = ?",
        (str(result.result_id),),
    ).fetchone()
    if row is not None:
        raise ValueError("research result already exists")
    connection.execute(
        "INSERT INTO research_results "
        "(result_id, run_id, provenance_fingerprint, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            str(result.result_id),
            result.spec.run_id,
            result.fingerprint,
            _json(research_result_to_payload(result)),
            result.completed_at,
        ),
    )


def _get_result(
    connection: sqlite3.Connection,
    result_id: UUID,
) -> ResearchResult | None:
    row = connection.execute(
        "SELECT run_id, provenance_fingerprint, payload FROM research_results WHERE result_id = ?",
        (str(result_id),),
    ).fetchone()
    if row is None:
        return None
    result = research_result_from_payload(_payload(row[2], "research result payload"))
    if result.result_id != result_id:
        raise ValueError("research result payload identity does not match row")
    if result.spec.run_id != row[0]:
        raise ValueError("research result run_id does not match row")
    if result.fingerprint != row[1]:
        raise ValueError("research result provenance fingerprint does not match row")
    return result


def _insert_manifest(
    connection: sqlite3.Connection,
    manifest: ResearchArtifactManifest,
    *,
    allow_existing: bool,
) -> None:
    manifest_fingerprint = manifest.fingerprint()
    payload = _json(manifest.canonical_payload())
    row = connection.execute(
        "SELECT run_fingerprint, payload FROM research_manifests WHERE manifest_fingerprint = ?",
        (manifest_fingerprint,),
    ).fetchone()
    if row is not None:
        if not allow_existing:
            raise ValueError("research artifact manifest already exists")
        if row[0] != manifest.run_fingerprint or row[1] != payload:
            raise ValueError("research artifact manifest identity conflict")
        return
    connection.execute(
        "INSERT INTO research_manifests "
        "(manifest_fingerprint, run_fingerprint, payload, created_at) "
        "VALUES (?, ?, ?, ?)",
        (
            manifest_fingerprint,
            manifest.run_fingerprint,
            payload,
            datetime.now(UTC).isoformat(),
        ),
    )


def _get_manifest(
    connection: sqlite3.Connection,
    manifest_fingerprint: str,
) -> ResearchArtifactManifest | None:
    row = connection.execute(
        "SELECT run_fingerprint, payload FROM research_manifests WHERE manifest_fingerprint = ?",
        (manifest_fingerprint,),
    ).fetchone()
    if row is None:
        return None
    manifest = research_manifest_from_payload(_payload(row[1], "research manifest payload"))
    if manifest.run_fingerprint != row[0]:
        raise ValueError("research manifest payload run fingerprint does not match row")
    if manifest.fingerprint() != manifest_fingerprint:
        raise ValueError("research manifest payload fingerprint does not match row")
    return manifest


def _run_from_row(
    connection: sqlite3.Connection,
    row: tuple[object, ...],
) -> ResearchRunRecord:
    (
        run_id,
        provenance_fingerprint,
        provenance_json,
        state,
        created_at,
        started_at,
        completed_at,
        result_id,
        failure_reason,
    ) = row
    run_id_text = str(run_id)
    provenance_fingerprint_text = str(provenance_fingerprint)
    provenance = research_provenance_from_payload(
        _payload(str(provenance_json), "research provenance payload")
    )
    if provenance.fingerprint() != provenance_fingerprint_text:
        raise ValueError("research run provenance fingerprint does not match row")

    manifest_rows = connection.execute(
        "SELECT manifest_fingerprint FROM research_run_manifests "
        "WHERE run_id = ? ORDER BY manifest_fingerprint",
        (run_id_text,),
    ).fetchall()
    fingerprints: list[str] = []
    for manifest_row in manifest_rows:
        manifest_fingerprint = str(manifest_row[0])
        manifest = _get_manifest(connection, manifest_fingerprint)
        if manifest is None:
            raise ValueError("research run references missing artifact manifest")
        if manifest.run_fingerprint != provenance_fingerprint_text:
            raise ValueError("research artifact manifest provenance does not match run")
        fingerprints.append(manifest_fingerprint)

    result_uuid = UUID(str(result_id)) if result_id is not None else None
    state_value = str(state)
    if state_value == ResearchRunState.COMPLETED.value:
        if result_uuid is None:
            raise ValueError("COMPLETED research run is missing result_id")
        result = _get_result(connection, result_uuid)
        if result is None:
            raise ValueError("COMPLETED research run references missing result")
        if result.spec.run_id != run_id_text:
            raise ValueError("research result run_id does not match stored run")
        if result.fingerprint != provenance_fingerprint_text:
            raise ValueError("research result provenance fingerprint does not match stored run")

    return ResearchRunRecord(
        run_id=run_id_text,
        provenance=provenance,
        state=ResearchRunState(state_value),
        created_at=str(created_at),
        started_at=None if started_at is None else str(started_at),
        completed_at=None if completed_at is None else str(completed_at),
        result_id=result_uuid,
        artifact_manifest_fingerprints=tuple(fingerprints),
        failure_reason=None if failure_reason is None else str(failure_reason),
    )


def _find_run(
    connection: sqlite3.Connection,
    run_id: str,
) -> ResearchRunRecord:
    if not run_id.strip():
        raise ValueError("run_id must not be empty")
    row = connection.execute(
        "SELECT run_id, provenance_fingerprint, provenance_json, state, created_at, "
        "started_at, completed_at, result_id, failure_reason "
        "FROM research_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"research run not found: {run_id}")
    return _run_from_row(connection, row)


def _update_run(
    connection: sqlite3.Connection,
    run: ResearchRunRecord,
) -> None:
    connection.execute(
        "UPDATE research_runs SET state = ?, started_at = ?, completed_at = ?, "
        "result_id = ?, failure_reason = ? WHERE run_id = ?",
        (
            run.state.value,
            run.started_at,
            run.completed_at,
            None if run.result_id is None else str(run.result_id),
            run.failure_reason,
            run.run_id,
        ),
    )


class SqliteResearchStore:
    """Durable research-result/manifest store using one SQLite database."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def save_result(self, result: ResearchResult) -> None:
        with self._database.transaction() as connection:
            _insert_result(connection, result)

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        with self._database.transaction() as connection:
            return _get_result(connection, result_id)

    def save_manifest(self, manifest: ResearchArtifactManifest) -> None:
        with self._database.transaction() as connection:
            _insert_manifest(connection, manifest, allow_existing=False)

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        if not manifest_id.strip():
            raise ValueError("manifest_id must not be empty")
        with self._database.transaction() as connection:
            return _get_manifest(connection, manifest_id)


class SqliteResearchRunRepository(ResearchRunRepository):
    """Durable research-run lifecycle repository with atomic output binding."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def create_run(self, run: ResearchRunRecord) -> ResearchRunRecord:
        if run.state is not ResearchRunState.CREATED:
            raise ValueError("research runs must be CREATED when first persisted")
        if run.artifact_manifest_fingerprints:
            raise ValueError("new research runs cannot pre-attach artifact manifests")
        with self._database.transaction() as connection:
            existing = connection.execute(
                "SELECT 1 FROM research_runs WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError("research run already exists")
            connection.execute(
                "INSERT INTO research_runs "
                "(run_id, provenance_fingerprint, provenance_json, state, created_at, "
                "started_at, completed_at, result_id, failure_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.provenance_fingerprint,
                    _json(run.provenance.canonical_payload()),
                    run.state.value,
                    run.created_at,
                    run.started_at,
                    run.completed_at,
                    None,
                    run.failure_reason,
                ),
            )
        return run

    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        with self._database.transaction() as connection:
            try:
                return _find_run(connection, run_id)
            except KeyError:
                return None

    def find_by_provenance_fingerprint(
        self, provenance_fingerprint: str
    ) -> tuple[ResearchRunRecord, ...]:
        if not provenance_fingerprint.strip():
            raise ValueError("provenance fingerprint must not be empty")
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT run_id, provenance_fingerprint, provenance_json, state, created_at, "
                "started_at, completed_at, result_id, failure_reason "
                "FROM research_runs WHERE provenance_fingerprint = ? "
                "ORDER BY created_at, run_id",
                (provenance_fingerprint,),
            ).fetchall()
            return tuple(_run_from_row(connection, row) for row in rows)

    def start_run(self, run_id: str, started_at: str) -> ResearchRunRecord:
        with self._database.transaction() as connection:
            current = _find_run(connection, run_id)
            updated = current.started(started_at)
            _update_run(connection, updated)
            return updated

    def complete_run(
        self, run_id: str, result: ResearchResult, completed_at: str
    ) -> ResearchRunRecord:
        with self._database.transaction() as connection:
            current = _find_run(connection, run_id)
            updated = current.completed(result, completed_at)
            _insert_result(connection, result)
            _update_run(connection, updated)
            return updated

    def attach_manifest(
        self,
        run_id: str,
        manifest: ResearchArtifactManifest,
    ) -> ResearchRunRecord:
        with self._database.transaction() as connection:
            current = _find_run(connection, run_id)
            updated = current.with_manifest(manifest)
            _insert_manifest(connection, manifest, allow_existing=True)
            connection.execute(
                "INSERT INTO research_run_manifests (run_id, manifest_fingerprint) VALUES (?, ?)",
                (run_id, manifest.fingerprint()),
            )
            return updated

    def fail_run(self, run_id: str, reason: str) -> ResearchRunRecord:
        with self._database.transaction() as connection:
            current = _find_run(connection, run_id)
            updated = current.failed(reason)
            _update_run(connection, updated)
            return updated


__all__ = ["SqliteResearchRunRepository", "SqliteResearchStore"]
