"""Application-level rehydration tests for durable research experiments."""

from pathlib import Path
from uuid import UUID

import pytest

from quantx.application import ExperimentReadService, ExperimentSnapshot
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteExperimentRepository,
    SqliteResearchRunRepository,
)
from quantx.research.artifacts import ResearchArtifactManifest
from quantx.research.experiments import Experiment, ExperimentRepository
from quantx.research.provenance import ResearchProvenance, ResearchRunConfiguration
from quantx.research.result import ResearchResult
from quantx.research.run import ResearchRunRecord
from quantx.research.storage import ResearchRunRepository

_EXPERIMENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _provenance() -> ResearchProvenance:
    return ResearchProvenance(
        dataset_id="dataset-1",
        dataset_version="v1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg1",
        run_configuration=ResearchRunConfiguration(),
    )


def _run(run_id: str, created_at: str) -> ResearchRunRecord:
    return ResearchRunRecord(
        run_id=run_id,
        provenance=_provenance(),
        created_at=created_at,
    )


def _experiment() -> Experiment:
    from datetime import datetime

    return Experiment(
        experiment_id=_EXPERIMENT_ID,
        name="parameter sweep",
        created_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )


def test_experiment_read_service_rehydrates_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "quantx.db"
    experiment = _experiment()
    first = _run("run-2", "2026-01-01T00:02:00Z")
    second = _run("run-1", "2026-01-01T00:01:00Z")

    with SqliteDatabase(path) as database:
        runs = SqliteResearchRunRepository(database)
        experiments = SqliteExperimentRepository(database)
        runs.create_run(first)
        runs.create_run(second)
        experiments.create_experiment(experiment)
        experiments.attach_run(experiment.experiment_id, first.run_id)
        experiments.attach_run(experiment.experiment_id, second.run_id)

        snapshot = ExperimentReadService(
            experiment_repository=experiments,
            run_repository=runs,
        ).get(experiment.experiment_id)

        assert snapshot == ExperimentSnapshot(
            experiment=experiment,
            runs=(second, first),
        )

    with SqliteDatabase(path) as reopened:
        snapshot = ExperimentReadService(
            experiment_repository=SqliteExperimentRepository(reopened),
            run_repository=SqliteResearchRunRepository(reopened),
        ).get(experiment.experiment_id)

        assert snapshot == ExperimentSnapshot(
            experiment=experiment,
            runs=(second, first),
        )


def test_experiment_read_service_returns_none_for_missing_experiment(tmp_path: Path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        service = ExperimentReadService(
            experiment_repository=SqliteExperimentRepository(database),
            run_repository=SqliteResearchRunRepository(database),
        )

        assert service.get(UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")) is None


class _MissingRunExperimentRepository(ExperimentRepository):
    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        return _experiment() if experiment_id == _EXPERIMENT_ID else None

    def experiments(self) -> tuple[Experiment, ...]:
        return (_experiment(),)

    def create_experiment(self, experiment: Experiment) -> Experiment:
        return experiment

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        return run_id

    def experiment_for_run(self, run_id: str) -> UUID | None:
        return _EXPERIMENT_ID

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]:
        return ("missing-run",)


class _EmptyRunRepository(ResearchRunRepository):
    def create_run(self, run: ResearchRunRecord) -> ResearchRunRecord:
        return run

    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        return None

    def find_by_provenance_fingerprint(
        self, provenance_fingerprint: str
    ) -> tuple[ResearchRunRecord, ...]:
        return ()

    def start_run(self, run_id: str, started_at: str) -> ResearchRunRecord:
        raise NotImplementedError

    def complete_run(
        self, run_id: str, result: ResearchResult, completed_at: str
    ) -> ResearchRunRecord:
        raise NotImplementedError

    def attach_manifest(
        self, run_id: str, manifest: ResearchArtifactManifest
    ) -> ResearchRunRecord:
        raise NotImplementedError

    def fail_run(self, run_id: str, reason: str) -> ResearchRunRecord:
        raise NotImplementedError


def test_experiment_read_service_fails_closed_for_missing_attached_run() -> None:
    service = ExperimentReadService(
        experiment_repository=_MissingRunExperimentRepository(),
        run_repository=_EmptyRunRepository(),
    )

    with pytest.raises(ValueError, match="references missing research run"):
        service.get(_EXPERIMENT_ID)


def test_snapshot_rejects_duplicate_run_ids() -> None:
    run = _run("run-1", "2026-01-01T00:00:00Z")

    with pytest.raises(ValueError, match="duplicate"):
        ExperimentSnapshot(experiment=_experiment(), runs=(run, run))


def test_snapshot_rejects_unsorted_runs() -> None:
    first = _run("run-1", "2026-01-01T00:01:00Z")
    second = _run("run-2", "2026-01-01T00:02:00Z")

    with pytest.raises(ValueError, match="deterministically ordered"):
        ExperimentSnapshot(experiment=_experiment(), runs=(second, first))


def test_experiment_read_service_does_not_require_result_store() -> None:
    service = ExperimentReadService(
        experiment_repository=_MissingRunExperimentRepository(),
        run_repository=_EmptyRunRepository(),
    )
    assert not hasattr(service, "_result_store")
