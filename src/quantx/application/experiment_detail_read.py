"""Read-side rehydration of durable experiments with authoritative run results."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from quantx.research.experiments import Experiment

from .experiment_read import ExperimentReadService
from .research_run_read import ResearchRunReadService, ResearchRunSnapshot


@dataclass(frozen=True, slots=True)
class ExperimentDetailSnapshot:
    """Persisted experiment plus authoritative snapshots for its attached runs."""

    experiment: Experiment
    runs: tuple[ResearchRunSnapshot, ...]

    def __post_init__(self) -> None:
        run_ids = tuple(snapshot.run.run_id for snapshot in self.runs)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("experiment detail snapshot cannot contain duplicate run_id values")
        if run_ids != tuple(sorted(run_ids)):
            raise ValueError("experiment detail snapshot runs must be deterministically ordered")


class ExperimentDetailReadService:
    """Compose experiment membership with authoritative run and result rehydration."""

    def __init__(
        self,
        *,
        experiment_read_service: ExperimentReadService,
        run_read_service: ResearchRunReadService,
    ) -> None:
        self._experiment_read_service = experiment_read_service
        self._run_read_service = run_read_service

    def get(self, experiment_id: UUID) -> ExperimentDetailSnapshot | None:
        """Return an experiment detail snapshot, or None when the experiment is absent."""
        experiment_snapshot = self._experiment_read_service.get(experiment_id)
        if experiment_snapshot is None:
            return None

        runs: list[ResearchRunSnapshot] = []
        for run in experiment_snapshot.runs:
            snapshot = self._run_read_service.get(run.run_id)
            if snapshot is None:
                raise ValueError(
                    f"experiment {experiment_id} references missing research run: {run.run_id}"
                )
            runs.append(snapshot)

        return ExperimentDetailSnapshot(
            experiment=experiment_snapshot.experiment,
            runs=tuple(runs),
        )


__all__ = ["ExperimentDetailReadService", "ExperimentDetailSnapshot"]
