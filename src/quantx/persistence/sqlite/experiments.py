"""SQLite persistence adapter for logical research experiments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from quantx.research.experiments import Experiment, ExperimentRepository

from .database import SqliteDatabase


def _experiment_from_row(row: tuple[object, ...]) -> Experiment:
    experiment_id = UUID(str(row[0]))
    created_at = datetime.fromisoformat(str(row[2]))
    return Experiment(
        experiment_id=experiment_id,
        name=str(row[1]),
        created_at=created_at,
    )


class SqliteExperimentRepository(ExperimentRepository):
    """Durable experiment catalog with explicit run membership."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def create_experiment(self, experiment: Experiment) -> Experiment:
        with self._database.transaction() as connection:
            existing = connection.execute(
                "SELECT 1 FROM research_experiments WHERE experiment_id = ?",
                (str(experiment.experiment_id),),
            ).fetchone()
            if existing is not None:
                raise ValueError("experiment already exists")
            connection.execute(
                "INSERT INTO research_experiments (experiment_id, name, created_at) "
                "VALUES (?, ?, ?)",
                (
                    str(experiment.experiment_id),
                    experiment.name,
                    experiment.created_at.isoformat(),
                ),
            )
        return experiment

    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT experiment_id, name, created_at "
                "FROM research_experiments WHERE experiment_id = ?",
                (str(experiment_id),),
            ).fetchone()
            return None if row is None else _experiment_from_row(row)

    def experiments(self) -> tuple[Experiment, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT experiment_id, name, created_at "
                "FROM research_experiments ORDER BY created_at, experiment_id"
            ).fetchall()
            return tuple(_experiment_from_row(row) for row in rows)

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")

        with self._database.transaction() as connection:
            experiment = connection.execute(
                "SELECT 1 FROM research_experiments WHERE experiment_id = ?",
                (str(experiment_id),),
            ).fetchone()
            if experiment is None:
                raise KeyError(f"experiment not found: {experiment_id}")

            run = connection.execute(
                "SELECT 1 FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"research run not found: {run_id}")

            existing = connection.execute(
                "SELECT experiment_id FROM research_experiment_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is not None:
                existing_experiment_id = UUID(str(existing[0]))
                if existing_experiment_id == experiment_id:
                    raise ValueError("research run already attached to experiment")
                raise ValueError("research run already attached to another experiment")

            connection.execute(
                "INSERT INTO research_experiment_runs (experiment_id, run_id) VALUES (?, ?)",
                (str(experiment_id), run_id),
            )
        return run_id

    def experiment_for_run(self, run_id: str) -> UUID | None:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")

        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT experiment_id FROM research_experiment_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return None if row is None else UUID(str(row[0]))

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]:
        with self._database.transaction() as connection:
            experiment = connection.execute(
                "SELECT 1 FROM research_experiments WHERE experiment_id = ?",
                (str(experiment_id),),
            ).fetchone()
            if experiment is None:
                raise KeyError(f"experiment not found: {experiment_id}")

            rows = connection.execute(
                "SELECT run_id FROM research_experiment_runs "
                "WHERE experiment_id = ? ORDER BY run_id",
                (str(experiment_id),),
            ).fetchall()
            return tuple(str(row[0]) for row in rows)


__all__ = ["SqliteExperimentRepository"]
