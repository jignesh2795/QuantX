import pytest
from uuid import UUID

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.provenance import ResearchProvenance
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import InMemoryResearchRunRepository


_RESULT_ID = UUID("00000000-0000-0000-0000-000000000001")


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
    actual_provenance = provenance or _provenance()
    return ResearchResult(
        spec=ResearchRunSpec(
            run_id=run_id,
            dataset_id=actual_provenance.dataset_id,
            dataset_version=actual_provenance.dataset_version,
            instrument_master_version=actual_provenance.instrument_master_version,
            market_rule_version=actual_provenance.market_rule_version,
            execution_model_version=actual_provenance.execution_model_version,
            simulation_profile=actual_provenance.simulation_profile,
            code_revision=actual_provenance.code_revision,
            configuration_revision=actual_provenance.configuration_revision,
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-01-01T00:01:00Z",
        completed_at="2026-01-01T00:02:00Z",
        time_range_start="2026-01-01T00:01:00Z",
        time_range_end="2026-01-01T00:01:00Z",
        result_id=result_id,
        provenance=actual_provenance,
    )


def _manifest(run: ResearchRunRecord, artifact_id: str = "dataset") -> ResearchArtifactManifest:
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


def test_new_run_is_created_and_exposes_provenance_identity() -> None:
    run = _run()

    assert run.state is ResearchRunState.CREATED
    assert run.result_id is None
    assert run.provenance_fingerprint == run.provenance.fingerprint()


def test_run_start_is_immutable_and_transitions_once() -> None:
    run = _run()

    started = run.started("2026-01-01T00:01:00Z")

    assert run.state is ResearchRunState.CREATED
    assert started.state is ResearchRunState.RUNNING
    assert started.started_at == "2026-01-01T00:01:00Z"
    assert started.provenance_fingerprint == run.provenance_fingerprint


def test_run_rejects_invalid_lifecycle_transitions() -> None:
    run = _run()
    started = run.started("2026-01-01T00:01:00Z")
    completed = started.completed(_result(), "2026-01-01T00:02:00Z")

    with pytest.raises(ValueError, match="cannot start"):
        started.started("2026-01-01T00:03:00Z")
    with pytest.raises(ValueError, match="cannot complete"):
        run.completed(_result(), "2026-01-01T00:02:00Z")
    with pytest.raises(ValueError, match="cannot fail"):
        completed.failed("too late")


def test_failed_runs_are_terminal() -> None:
    failed = _run().failed("data unavailable")

    assert failed.state is ResearchRunState.FAILED
    assert failed.failure_reason == "data unavailable"

    with pytest.raises(ValueError, match="cannot start"):
        failed.started("2026-01-01T00:01:00Z")
    with pytest.raises(ValueError, match="cannot fail"):
        failed.failed("another failure")
    with pytest.raises(ValueError, match="FAILED"):
        failed.with_manifest(_manifest(failed))


def test_complete_binds_matching_result() -> None:
    run = _run().started("2026-01-01T00:01:00Z")
    result = _result()

    completed = run.completed(result, "2026-01-01T00:02:00Z")

    assert completed.state is ResearchRunState.COMPLETED
    assert completed.result_id == result.result_id
    assert completed.provenance_fingerprint == result.fingerprint


def test_complete_rejects_result_from_different_run_instance() -> None:
    run = _run().started("2026-01-01T00:01:00Z")

    with pytest.raises(ValueError, match="run_id"):
        run.completed(_result(run_id="run-2"), "2026-01-01T00:02:00Z")


def test_complete_rejects_result_with_different_provenance_identity() -> None:
    run = _run().started("2026-01-01T00:01:00Z")
    different = _provenance(dataset_id="dataset-2")

    with pytest.raises(ValueError, match="provenance fingerprint"):
        run.completed(_result(provenance=different), "2026-01-01T00:02:00Z")


def test_manifest_must_match_run_provenance() -> None:
    run = _run()

    assert run.with_manifest(_manifest(run)).artifact_manifest_fingerprints

    different_manifest = ResearchArtifactManifest(
        run_fingerprint=_provenance(dataset_id="dataset-2").fingerprint(),
        artifacts=(),
    )
    with pytest.raises(ValueError, match="run fingerprint"):
        run.with_manifest(different_manifest)


def test_manifest_attachment_is_idempotency_strict() -> None:
    run = _run()
    manifest = _manifest(run)

    attached = run.with_manifest(manifest)

    with pytest.raises(ValueError, match="already attached"):
        attached.with_manifest(manifest)


def test_completed_run_can_receive_late_artifact_association() -> None:
    run = _run().started("2026-01-01T00:01:00Z")
    completed = run.completed(_result(), "2026-01-01T00:02:00Z")

    attached = completed.with_manifest(_manifest(completed))

    assert attached.state is ResearchRunState.COMPLETED
    assert len(attached.artifact_manifest_fingerprints) == 1


def test_repository_rejects_duplicate_run_id() -> None:
    repository = InMemoryResearchRunRepository()
    run = _run()

    repository.create_run(run)

    with pytest.raises(ValueError, match="already exists"):
        repository.create_run(run)


def test_repository_supports_many_runs_with_one_provenance_identity() -> None:
    repository = InMemoryResearchRunRepository()
    first = _run(run_id="run-1", created_at="2026-01-01T00:00:00Z")
    second = _run(run_id="run-2", created_at="2026-01-01T00:02:00Z")

    repository.create_run(first)
    repository.create_run(second)

    matches = repository.find_by_provenance_fingerprint(first.provenance_fingerprint)

    assert [item.run_id for item in matches] == ["run-1", "run-2"]


def test_repository_lifecycle_operations_replace_immutable_snapshots() -> None:
    repository = InMemoryResearchRunRepository()
    run = _run()

    repository.create_run(run)
    started = repository.start_run("run-1", "2026-01-01T00:01:00Z")
    completed = repository.complete_run(
        "run-1",
        _result(),
        "2026-01-01T00:02:00Z",
    )

    assert repository.get_run("run-1") == completed
    assert started.result_id is None
    assert completed.state is ResearchRunState.COMPLETED


def test_repository_manifest_and_failure_operations() -> None:
    repository = InMemoryResearchRunRepository()
    first = _run(run_id="run-1")
    second = _run(run_id="run-2")

    repository.create_run(first)
    repository.create_run(second)

    attached = repository.attach_manifest("run-1", _manifest(first))
    failed = repository.fail_run("run-2", "execution error")

    assert len(attached.artifact_manifest_fingerprints) == 1
    assert failed.state is ResearchRunState.FAILED


def test_repository_missing_run_fails_closed() -> None:
    repository = InMemoryResearchRunRepository()

    with pytest.raises(KeyError, match="research run not found"):
        repository.start_run("missing", "2026-01-01T00:01:00Z")
