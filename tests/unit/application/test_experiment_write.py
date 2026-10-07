"""Application-level tests for the durable experiment write boundary."""

from datetime import datetime
from uuid import UUID

import pytest

from quantx.application import ExperimentWriteService
from quantx.research.experiments import Experiment, ExperimentRepository

_EXPERIMENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _RecordingExperimentRepository(ExperimentRepository):
    def __init__(self) -> None:
        self.created: list[Experiment] = []
        self.attachments: list[tuple[UUID, str]] = []
        self.create_error: Exception | None = None
        self.attach_error: Exception | None = None

    def create_experiment(self, experiment: Experiment) -> Experiment:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(experiment)
        return experiment

    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        return None

    def experiments(self) -> tuple[Experiment, ...]:
        return ()

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        if self.attach_error is not None:
            raise self.attach_error
        self.attachments.append((experiment_id, run_id))
        return run_id

    def experiment_for_run(self, run_id: str) -> UUID | None:
        return None

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]:
        return ()


def _experiment() -> Experiment:
    return Experiment(
        experiment_id=_EXPERIMENT_ID,
        name="parameter sweep",
        created_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )


def test_create_delegates_unchanged_experiment_to_repository() -> None:
    repository = _RecordingExperimentRepository()
    service = ExperimentWriteService(repository=repository)

    experiment = _experiment()

    created = service.create(experiment)

    assert created is experiment
    assert repository.created == [experiment]


def test_attach_run_delegates_membership_to_repository() -> None:
    repository = _RecordingExperimentRepository()
    service = ExperimentWriteService(repository=repository)

    run_id = service.attach_run(_EXPERIMENT_ID, "run-1")

    assert run_id == "run-1"
    assert repository.attachments == [(_EXPERIMENT_ID, "run-1")]


def test_create_propagates_repository_failure_without_translation() -> None:
    error = ValueError("experiment already exists")
    repository = _RecordingExperimentRepository()
    repository.create_error = error
    service = ExperimentWriteService(repository=repository)

    with pytest.raises(ValueError, match="experiment already exists") as exc_info:
        service.create(_experiment())

    assert exc_info.value is error
    assert repository.created == []


def test_attach_run_propagates_repository_failure_without_translation() -> None:
    error = KeyError("research run not found: run-1")
    repository = _RecordingExperimentRepository()
    repository.attach_error = error
    service = ExperimentWriteService(repository=repository)

    with pytest.raises(KeyError, match="research run not found: run-1"):
        service.attach_run(_EXPERIMENT_ID, "run-1")

    assert repository.attachments == []
