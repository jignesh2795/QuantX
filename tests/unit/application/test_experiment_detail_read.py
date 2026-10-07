"""Application-level tests for experiment detail rehydration."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest

from quantx.application import (
    ExperimentDetailReadService,
    ExperimentReadService,
    ResearchRunReadService,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteExperimentRepository
from quantx.research.experiments import Experiment, ExperimentRepository
from quantx.research.provenance import ResearchProvenance
from quantx.research.result import ResearchResult, ResearchRunSpec
from quantx.research.run import ResearchRunRecord
from quantx.research.storage import (
    InMemoryResearchRunRepository,
    InMemoryResearchStore,
    ResearchRunRepository,
)


_EXPERIMENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _experiment() -> Experiment:
    return Experiment(
        experiment_id=_EXPERIMENT_ID,
        name="parameter sweep",
        created_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )


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
    )


def _result(run_id: str, result_id: UUID) -> ResearchResult:
    spec = ResearchRunSpec(
        run_id=run_id,
        dataset_id="dataset-1",
        dataset_version="v1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg1",
    )
    return ResearchResult(
        spec=spec,
        quality="COMPLETE_OBSERVED",
        started_at="2026-01-01T00:01:00+00:00",
        completed_at="2026-01-01T00:02:00+00:00",
        time_range_start="2026-01-01T00:01:00+00:00",
        time_range_end="2026-01-01T00:02:00+00:00",
        metrics=(("pnl", Decimal("10")),),
        result_id=result_id,
    )


def _service(
    experiment_repository: ExperimentRepository,
    run_repository: InMemoryResearchRunRepository,
    result_store: InMemoryResearchStore,
) -> ExperimentDetailReadService:
    return ExperimentDetailReadService(
        experiment_read_service=ExperimentReadService(
            experiment_repository=experiment_repository,
            run_repository=run_repository,
        ),
        run_read_service=ResearchRunReadService(
            run_repository=run_repository,
            result_store=result_store,
        ),
    )


class _ExperimentRepository(ExperimentRepository):
    def __init__(self, experiment: Experiment, run_ids: tuple[str, ...]) -> None:
        self._experiment = experiment
        self._run_ids = run_ids

    def create_experiment(self, experiment: Experiment) -> Experiment:
        self._experiment = experiment
        return experiment

    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        return self._experiment if experiment_id == self._experiment.experiment_id else None

    def experiments(self) -> tuple[Experiment, ...]:
        return (self._experiment,)

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        raise NotImplementedError

    def experiment_for_run(self, run_id: str) -> UUID | None:
        return self._experiment.experiment_id if run_id in self._run_ids else None

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]:
        return self._run_ids if experiment_id == self._experiment.experiment_id else ()


def _persist_run(
    run_repository: InMemoryResearchRunRepository,
    result_store: InMemoryResearchStore,
    result: ResearchResult,
) -> None:
    run_repository.create_run(
        ResearchRunRecord(
            run_id=result.spec.run_id,
            provenance=_provenance(),
            created_at=result.started_at,
        )
    )
    run_repository.start_run(result.spec.run_id, result.started_at)
    result_store.save_result(result)
    run_repository.complete_run(result.spec.run_id, result, result.completed_at)


def test_detail_read_rehydrates_experiment_runs_and_results() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    left = _result("run-2", UUID("11111111-1111-1111-1111-111111111111"))
    right = _result("run-1", UUID("22222222-2222-2222-2222-222222222222"))
    _persist_run(run_repository, result_store, left)
    _persist_run(run_repository, result_store, right)

    service = _service(
        _ExperimentRepository(_experiment(), ("run-1", "run-2")),
        run_repository,
        result_store,
    )

    snapshot = service.get(_EXPERIMENT_ID)

    assert snapshot is not None
    assert snapshot.experiment == _experiment()
    assert tuple(item.run.run_id for item in snapshot.runs) == ("run-1", "run-2")
    assert tuple(item.result.result_id for item in snapshot.runs if item.result is not None) == (
        right.result_id,
        left.result_id,
    )


def test_detail_read_returns_none_for_missing_experiment() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    service = _service(_ExperimentRepository(_experiment(), ()), run_repository, result_store)

    assert service.get(UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")) is None


def test_detail_read_preserves_non_completed_runs_without_results() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    run = ResearchRunRecord(
        run_id="running",
        provenance=_provenance(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    run_repository.create_run(run)
    run_repository.start_run(run.run_id, "2026-01-01T00:01:00+00:00")

    service = _service(_ExperimentRepository(_experiment(), ("running",)), run_repository, result_store)

    snapshot = service.get(_EXPERIMENT_ID)

    assert snapshot is not None
    assert snapshot.runs[0].result is None


def test_detail_read_fails_closed_for_completed_run_without_result() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    run = ResearchRunRecord(
        run_id="completed",
        provenance=_provenance(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    run_repository.create_run(run)
    run_repository.start_run(run.run_id, "2026-01-01T00:01:00+00:00")
    completed = run_repository.get_run(run.run_id)
    assert completed is not None
    result = ResearchResult(
        spec=ResearchRunSpec(
            run_id=run.run_id,
            dataset_id="dataset-1",
            dataset_version="v1",
            instrument_master_version="instrument-v1",
            market_rule_version="rules-v1",
            execution_model_version="paper-v1",
            simulation_profile="REALISTIC",
            code_revision="abc123",
            configuration_revision="cfg1",
        ),
        quality="COMPLETE_OBSERVED",
        started_at="2026-01-01T00:01:00+00:00",
        completed_at="2026-01-01T00:02:00+00:00",
        time_range_start="2026-01-01T00:01:00+00:00",
        time_range_end="2026-01-01T00:02:00+00:00",
        result_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    run_repository.complete_run(run.run_id, result, result.completed_at)

    service = _service(_ExperimentRepository(_experiment(), ("completed",)), run_repository, result_store)

    with pytest.raises(ValueError, match="requires a persisted result"):
        service.get(_EXPERIMENT_ID)


def test_detail_read_requires_existing_membership_run() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    service = _service(
        _ExperimentRepository(_experiment(), ("missing",)),
        run_repository,
        result_store,
    )

    with pytest.raises(ValueError, match="references missing research run"):
        service.get(_EXPERIMENT_ID)


class _UnusedSqliteMarker:
    """Keep the SQLite import out of application semantics; integration stays in E."""


assert SqliteDatabase is not None
assert SqliteExperimentRepository is not None
assert ResearchRunRepository is not None
assert _UnusedSqliteMarker is not None
