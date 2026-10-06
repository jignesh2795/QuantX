"""SQLite research persistence and transaction-boundary invariants."""

import sqlite3
from decimal import Decimal
from uuid import UUID

import pytest

from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteResearchRunRepository,
    SqliteResearchStore,
)
from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.provenance import ResearchProvenance, ResearchRunConfiguration
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunRecord, ResearchRunState

_RESULT_ID = UUID("00000000-0000-0000-0000-000000000010")


def _provenance(dataset_id: str = "dataset-1") -> ResearchProvenance:
    return ResearchProvenance(
        dataset_id=dataset_id,
        dataset_version="v1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg1",
        run_configuration=ResearchRunConfiguration(),
    )


def _run(
    run_id: str = "run-1",
    provenance: ResearchProvenance | None = None,
    created_at: str = "2026-01-01T00:00:00Z",
) -> ResearchRunRecord:
    return ResearchRunRecord(
        run_id=run_id,
        provenance=provenance or _provenance(),
        created_at=created_at,
    )


def _result(
    run_id: str = "run-1",
    provenance: ResearchProvenance | None = None,
    result_id: UUID = _RESULT_ID,
) -> ResearchResult:
    actual = provenance or _provenance()
    return ResearchResult(
        spec=ResearchRunSpec(
            run_id=run_id,
            dataset_id=actual.dataset_id,
            dataset_version=actual.dataset_version,
            instrument_master_version=actual.instrument_master_version,
            market_rule_version=actual.market_rule_version,
            execution_model_version=actual.execution_model_version,
            simulation_profile=actual.simulation_profile,
            code_revision=actual.code_revision,
            configuration_revision=actual.configuration_revision,
            run_configuration=actual.run_configuration,
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-01-01T00:01:00Z",
        completed_at="2026-01-01T00:02:00Z",
        time_range_start="2026-01-01T00:01:00Z",
        time_range_end="2026-01-01T00:01:00Z",
        metrics=(("net_pnl", Decimal("10")),),
        result_id=result_id,
        provenance=actual,
    )


def _manifest(run: ResearchRunRecord, artifact_id: str = "artifact-1") -> ResearchArtifactManifest:
    return ResearchArtifactManifest(
        run_fingerprint=run.provenance_fingerprint,
        artifacts=(
            ResearchArtifact(
                artifact_id=artifact_id,
                artifact_type="dataset",
                content_hash=f"sha256:{artifact_id}",
                uri=f"file:///{artifact_id}.bin",
            ),
        ),
    )


def test_sqlite_research_result_and_manifest_round_trip(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    run = _run()
    result = _result(provenance=run.provenance)
    manifest = _manifest(run)

    with SqliteDatabase(path) as database:
        store = SqliteResearchStore(database)
        store.save_result(result)
        store.save_manifest(manifest)

        assert store.get_result(result.result_id) == result
        assert store.get_manifest(manifest.fingerprint()) == manifest

    with SqliteDatabase(path) as reopened:
        store = SqliteResearchStore(reopened)
        assert store.get_result(result.result_id) == result
        assert store.get_manifest(manifest.fingerprint()) == manifest


def test_sqlite_research_store_rejects_duplicate_result_and_manifest(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteResearchStore(database)
        run = _run()
        result = _result(provenance=run.provenance)
        manifest = _manifest(run)
        store.save_result(result)
        store.save_manifest(manifest)

        with pytest.raises(ValueError, match="result already exists"):
            store.save_result(result)
        with pytest.raises(ValueError, match="manifest already exists"):
            store.save_manifest(manifest)


def test_research_result_row_metadata_is_verified_on_read(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    run = _run()
    result = _result(provenance=run.provenance)

    with SqliteDatabase(path) as database:
        store = SqliteResearchStore(database)
        store.save_result(result)
        with database.transaction() as connection:
            connection.execute(
                "UPDATE research_results SET provenance_fingerprint = ? WHERE result_id = ?",
                ("tampered", str(result.result_id)),
            )
        with pytest.raises(ValueError, match="provenance fingerprint"):
            store.get_result(result.result_id)

    with SqliteDatabase(path) as database:
        with database.transaction() as connection:
            connection.execute(
                "UPDATE research_results SET provenance_fingerprint = ?, run_id = ? "
                "WHERE result_id = ?",
                (result.fingerprint, "tampered-run", str(result.result_id)),
            )
        with pytest.raises(ValueError, match="run_id"):
            SqliteResearchStore(database).get_result(result.result_id)


def test_run_lifecycle_and_structured_provenance_survive_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    run = _run()
    result = _result(provenance=run.provenance)

    with SqliteDatabase(path) as database:
        repository = SqliteResearchRunRepository(database)
        assert repository.create_run(run) == run
        started = repository.start_run(run.run_id, "2026-01-01T00:01:00Z")
        completed = repository.complete_run(run.run_id, result, "2026-01-01T00:02:00Z")
        assert started.state is ResearchRunState.RUNNING
        assert completed.state is ResearchRunState.COMPLETED

    with SqliteDatabase(path) as reopened:
        repository = SqliteResearchRunRepository(reopened)
        restored = repository.get_run(run.run_id)
        assert restored == completed
        assert restored is not None
        assert restored.provenance.run_configuration == run.provenance.run_configuration
        assert SqliteResearchStore(reopened).get_result(result.result_id) == result


def test_many_runs_share_one_provenance_fingerprint(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        first = _run("run-1", created_at="2026-01-01T00:00:00Z")
        second = _run("run-2", created_at="2026-01-01T00:02:00Z")
        repository.create_run(first)
        repository.create_run(second)

        matches = repository.find_by_provenance_fingerprint(first.provenance_fingerprint)

        assert [run.run_id for run in matches] == ["run-1", "run-2"]


def test_run_duplicate_and_missing_lookup_fail_closed(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)

        with pytest.raises(ValueError, match="already exists"):
            repository.create_run(run)
        assert repository.get_run("missing") is None
        with pytest.raises(ValueError, match="must not be empty"):
            repository.find_by_provenance_fingerprint("")


def test_run_result_mismatch_is_rejected_without_persisting_result(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        repository.start_run(run.run_id, "2026-01-01T00:01:00Z")
        bad = _result(run_id="run-2", provenance=run.provenance)

        with pytest.raises(ValueError, match="run_id"):
            repository.complete_run(run.run_id, bad, "2026-01-01T00:02:00Z")

        restored = repository.get_run(run.run_id)
        assert restored is not None
        assert restored.state is ResearchRunState.RUNNING
        assert SqliteResearchStore(database).get_result(_RESULT_ID) is None


def test_complete_is_atomic_when_run_update_fails(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        repository.start_run(run.run_id, "2026-01-01T00:01:00Z")
        database.connection().execute(
            """
            CREATE TRIGGER fail_research_completion
            BEFORE UPDATE OF state ON research_runs
            WHEN NEW.state = 'COMPLETED'
            BEGIN
                SELECT RAISE(ABORT, 'forced research completion failure');
            END
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="forced research completion failure"):
            repository.complete_run(
                run.run_id,
                _result(provenance=run.provenance),
                "2026-01-01T00:02:00Z",
            )

        restored = repository.get_run(run.run_id)
        assert restored is not None
        assert restored.state is ResearchRunState.RUNNING
        assert SqliteResearchStore(database).get_result(_RESULT_ID) is None


def test_manifest_attachment_is_persisted_and_shareable(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        first = _run("run-1")
        second = _run("run-2")
        manifest = _manifest(first)
        repository.create_run(first)
        repository.create_run(second)

        attached_first = repository.attach_manifest(first.run_id, manifest)
        attached_second = repository.attach_manifest(second.run_id, manifest)

        assert attached_first.artifact_manifest_fingerprints == (manifest.fingerprint(),)
        assert attached_second.artifact_manifest_fingerprints == (manifest.fingerprint(),)


def test_manifest_mismatch_does_not_persist(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        bad = _manifest(_run(provenance=_provenance("other")))

        with pytest.raises(ValueError, match="run fingerprint"):
            repository.attach_manifest(run.run_id, bad)

        restored = repository.get_run(run.run_id)
        assert restored is not None
        assert restored.artifact_manifest_fingerprints == ()
        assert SqliteResearchStore(database).get_manifest(bad.fingerprint()) is None


def test_completed_run_allows_late_manifest_attachment(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        repository.start_run(run.run_id, "2026-01-01T00:01:00Z")
        completed = repository.complete_run(
            run.run_id,
            _result(provenance=run.provenance),
            "2026-01-01T00:02:00Z",
        )

        attached = repository.attach_manifest(run.run_id, _manifest(completed))
        assert attached.state is ResearchRunState.COMPLETED
        assert len(attached.artifact_manifest_fingerprints) == 1


def test_failed_run_rejects_manifest_and_lifecycle_reopen(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        failed = repository.fail_run(run.run_id, "data unavailable")

        with pytest.raises(ValueError, match="FAILED"):
            repository.attach_manifest(run.run_id, _manifest(failed))
        with pytest.raises(ValueError, match="cannot start"):
            repository.start_run(run.run_id, "2026-01-01T00:03:00Z")
        with pytest.raises(ValueError, match="cannot fail"):
            repository.fail_run(run.run_id, "again")


def test_completed_run_corruption_is_detected(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        repository.create_run(run)
        repository.start_run(run.run_id, "2026-01-01T00:01:00Z")
        result = _result(provenance=run.provenance)
        repository.complete_run(run.run_id, result, "2026-01-01T00:02:00Z")
        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM research_results WHERE result_id = ?",
                (str(result.result_id),),
            )

        with pytest.raises(ValueError, match="missing result"):
            repository.get_run(run.run_id)


def test_run_create_rejects_pre_attached_manifest_snapshot(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteResearchRunRepository(database)
        run = _run()
        attached = ResearchRunRecord(
            run_id=run.run_id,
            provenance=run.provenance,
            created_at=run.created_at,
            artifact_manifest_fingerprints=("abc",),
        )

        with pytest.raises(ValueError, match="pre-attach"):
            repository.create_run(attached)


def test_transaction_rollback_leaves_no_research_rows(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        store = SqliteResearchStore(database)
        result = _result()
        with pytest.raises(RuntimeError, match="boom"):
            with database.transaction() as connection:
                store.save_result(result)
                store.save_manifest(_manifest(_run()))
                raise RuntimeError("boom")

        assert store.get_result(result.result_id) is None
