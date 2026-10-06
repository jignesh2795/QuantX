"""SQLite persistence tests for the durable experiment catalog."""

import sqlite3
from uuid import UUID

import pytest

from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteExperimentRepository,
    SqliteResearchRunRepository,
)
from quantx.research.experiments import Experiment
from quantx.research.provenance import ResearchProvenance, ResearchRunConfiguration
from quantx.research.run import ResearchRunRecord

_EXPERIMENT_ONE = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_EXPERIMENT_TWO = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


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


def _run(run_id: str = "run-1") -> ResearchRunRecord:
    return ResearchRunRecord(
        run_id=run_id,
        provenance=_provenance(),
        created_at="2026-01-01T00:00:00Z",
    )


def _experiment(
    experiment_id: UUID = _EXPERIMENT_ONE,
    *,
    name: str = "baseline",
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> Experiment:
    from datetime import datetime

    return Experiment(
        experiment_id=experiment_id,
        name=name,
        created_at=datetime.fromisoformat(created_at),
    )


def test_experiment_catalog_round_trips_after_restart(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    experiment = _experiment()
    run = _run()

    with SqliteDatabase(path) as database:
        runs = SqliteResearchRunRepository(database)
        experiments = SqliteExperimentRepository(database)
        runs.create_run(run)
        assert experiments.create_experiment(experiment) == experiment
        assert experiments.attach_run(experiment.experiment_id, run.run_id) == run.run_id

        assert experiments.get_experiment(experiment.experiment_id) == experiment
        assert experiments.experiment_for_run(run.run_id) == experiment.experiment_id
        assert experiments.runs_for_experiment(experiment.experiment_id) == (run.run_id,)

    with SqliteDatabase(path) as reopened:
        experiments = SqliteExperimentRepository(reopened)
        assert experiments.get_experiment(experiment.experiment_id) == experiment
        assert experiments.experiment_for_run(run.run_id) == experiment.experiment_id
        assert experiments.runs_for_experiment(experiment.experiment_id) == (run.run_id,)


def test_create_experiment_rejects_duplicate_identity(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        experiment = _experiment()
        repository.create_experiment(experiment)

        with pytest.raises(ValueError, match="experiment already exists"):
            repository.create_experiment(experiment)


def test_experiments_are_returned_in_deterministic_order(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        first = _experiment(
            _EXPERIMENT_ONE,
            name="first",
            created_at="2026-01-01T00:02:00+00:00",
        )
        second = _experiment(
            _EXPERIMENT_TWO,
            name="second",
            created_at="2026-01-01T00:01:00+00:00",
        )
        repository.create_experiment(first)
        repository.create_experiment(second)

        assert repository.experiments() == (second, first)


def test_attach_requires_existing_experiment_and_run(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        experiment = _experiment()

        with pytest.raises(KeyError, match="experiment not found"):
            repository.attach_run(experiment.experiment_id, "run-1")

        repository.create_experiment(experiment)
        with pytest.raises(KeyError, match="research run not found"):
            repository.attach_run(experiment.experiment_id, "run-1")


def test_attach_rejects_empty_run_id(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        repository.create_experiment(_experiment())

        with pytest.raises(ValueError, match="run_id"):
            repository.attach_run(_EXPERIMENT_ONE, "   ")


def test_attach_rejects_duplicate_and_cross_experiment_membership(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        runs = SqliteResearchRunRepository(database)
        repository = SqliteExperimentRepository(database)
        runs.create_run(_run())
        repository.create_experiment(_experiment(_EXPERIMENT_ONE, name="first"))
        repository.create_experiment(_experiment(_EXPERIMENT_TWO, name="second"))

        repository.attach_run(_EXPERIMENT_ONE, "run-1")

        with pytest.raises(ValueError, match="already attached to experiment"):
            repository.attach_run(_EXPERIMENT_ONE, "run-1")

        with pytest.raises(ValueError, match="another experiment"):
            repository.attach_run(_EXPERIMENT_TWO, "run-1")

        assert repository.experiment_for_run("run-1") == _EXPERIMENT_ONE
        assert repository.runs_for_experiment(_EXPERIMENT_TWO) == ()


def test_runs_for_experiment_are_sorted_by_run_id(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        runs = SqliteResearchRunRepository(database)
        repository = SqliteExperimentRepository(database)
        repository.create_experiment(_experiment())
        runs.create_run(_run("run-2"))
        runs.create_run(_run("run-1"))

        repository.attach_run(_EXPERIMENT_ONE, "run-2")
        repository.attach_run(_EXPERIMENT_ONE, "run-1")

        assert repository.runs_for_experiment(_EXPERIMENT_ONE) == ("run-1", "run-2")


def test_lookup_rejects_empty_run_id_and_missing_membership_is_none(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        with pytest.raises(ValueError, match="run_id"):
            repository.experiment_for_run("")

        assert repository.experiment_for_run("missing") is None


def test_unknown_experiment_lookup_fails_closed(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        repository = SqliteExperimentRepository(database)
        with pytest.raises(KeyError, match="experiment not found"):
            repository.runs_for_experiment(UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"))


def test_schema_stores_only_experiment_metadata_and_run_membership(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        connection = database.connection()
        experiment_columns = [
            row[1] for row in connection.execute(
                "PRAGMA table_info(research_experiments)"
            ).fetchall()
        ]
        membership_columns = [
            row[1] for row in connection.execute(
                "PRAGMA table_info(research_experiment_runs)"
            ).fetchall()
        ]

    assert experiment_columns == ["experiment_id", "name", "created_at"]
    assert membership_columns == ["experiment_id", "run_id"]


def test_database_enforces_one_experiment_per_run(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        runs = SqliteResearchRunRepository(database)
        repository = SqliteExperimentRepository(database)
        runs.create_run(_run())
        repository.create_experiment(_experiment(_EXPERIMENT_ONE, name="first"))
        repository.create_experiment(_experiment(_EXPERIMENT_TWO, name="second"))
        repository.attach_run(_EXPERIMENT_ONE, "run-1")

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO research_experiment_runs (experiment_id, run_id) VALUES (?, ?)",
                    (str(_EXPERIMENT_TWO), "run-1"),
                )

        assert repository.experiment_for_run("run-1") == _EXPERIMENT_ONE


def test_catalog_transaction_rolls_back_metadata_and_membership_together(tmp_path) -> None:
    path = tmp_path / "quantx.db"

    with SqliteDatabase(path) as database:
        runs = SqliteResearchRunRepository(database)
        repository = SqliteExperimentRepository(database)
        run = _run()
        runs.create_run(run)

        with pytest.raises(RuntimeError, match="boom"):
            with database.transaction():
                repository.create_experiment(_experiment())
                repository.attach_run(_EXPERIMENT_ONE, run.run_id)
                raise RuntimeError("boom")

        assert repository.get_experiment(_EXPERIMENT_ONE) is None
        assert repository.experiment_for_run(run.run_id) is None

    with SqliteDatabase(path) as reopened:
        repository = SqliteExperimentRepository(reopened)
        assert repository.get_experiment(_EXPERIMENT_ONE) is None
        assert repository.experiment_for_run("run-1") is None
