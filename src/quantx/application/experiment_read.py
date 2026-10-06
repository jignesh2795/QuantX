"""Read-side rehydration of durable research experiments and their runs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from quantx.research.experiments import Experiment, ExperimentRepository
from quantx.research.run import ResearchRunRecord, ResearchRunRepository


@dataclass(frozen=True, slots=True)
class ExperimentSnapshot:
    """Persisted experiment plus its attached research runs."""

    experiment: Experiment
    runs: tuple[ResearchRunRecord, ...]

    def __post_init__(self) -> None:
        run_ids = tuple(run.run_id for run in self.runs)
        if any(not run_id.strip() for run_id in run_ids):
            raise ValueError("experiment snapshot cannot contain a blank run_id")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("experiment snapshot cannot contain duplicate run_id values")
        if run_ids != tuple(sorted(run_ids)):
            raise ValueError("experiment snapshot runs must be deterministically ordered")


class ExperimentReadService:
    """Rehydrate an experiment from its catalog and authoritative run repository."""

    def __init__(
        self,
        *,
        experiment_repository: ExperimentRepository,
        run_repository: ResearchRunRepository,
    ) -> None:
        self._experiment_repository = experiment_repository
        self._run_repository = run_repository

    def get(self, experiment_id: UUID) -> ExperimentSnapshot | None:
        """Return a validated persisted experiment snapshot, or None when absent."""
        experiment = self._experiment_repository.get_experiment(experiment_id)
        if experiment is None:
            return None

        run_ids = self._experiment_repository.runs_for_experiment(experiment_id)
        runs: list[ResearchRunRecord] = []
        for run_id in run_ids:
            run = self._run_repository.get_run(run_id)
            if run is None:
                raise ValueError(
                    f"experiment {experiment_id} references missing research run: {run_id}"
                )
            owner = self._experiment_repository.experiment_for_run(run_id)
            if owner != experiment_id:
                raise ValueError(
                    f"research run {run_id} has inconsistent experiment ownership"
                )
            runs.append(run)

        return ExperimentSnapshot(experiment=experiment, runs=tuple(runs))


__all__ = ["ExperimentReadService", "ExperimentSnapshot"]
