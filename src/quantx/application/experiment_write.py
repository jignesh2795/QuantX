"""Application write boundary for durable research experiments."""

from __future__ import annotations

from uuid import UUID

from quantx.research.experiments import Experiment, ExperimentRepository


class ExperimentWriteService:
    """Coordinate durable experiment creation and run membership commands."""

    def __init__(self, *, repository: ExperimentRepository) -> None:
        self._repository = repository

    def create(self, experiment: Experiment) -> Experiment:
        """Persist one logical experiment without duplicating repository rules."""
        return self._repository.create_experiment(experiment)

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        """Attach one existing research run through the durable repository boundary."""
        return self._repository.attach_run(experiment_id, run_id)


__all__ = ["ExperimentWriteService"]
