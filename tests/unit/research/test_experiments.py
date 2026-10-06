from decimal import Decimal
from uuid import UUID

import pytest

from quantx.research.experiments import Experiment, ExperimentManager
from quantx.research.provenance import (
    ExecutionConfiguration,
    ResearchRunConfiguration,
    StrategyConfiguration,
)
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality


def _spec(
    run_id: str,
    dataset: str,
    *,
    simulation_profile: str = "REALISTIC",
    strategy_id: str | None = None,
) -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id=run_id,
        dataset_id=dataset,
        dataset_version="v1",
        instrument_master_version="instruments-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile=simulation_profile,
        code_revision="abc123",
        configuration_revision="cfg1",
        run_configuration=(
            ResearchRunConfiguration(
                strategy=StrategyConfiguration(
                    strategy_id=strategy_id,
                    strategy_version="v1",
                ),
                execution=ExecutionConfiguration(
                    simulation_profile_name=simulation_profile,
                    latency_ms=0,
                ),
            )
            if strategy_id is not None
            else None
        ),
    )


def _result(
    dataset: str,
    strategy: str,
    metrics: tuple[tuple[str, Decimal], ...],
    *,
    simulation_profile: str = "REALISTIC",
    structured_strategy: bool = False,
) -> ResearchResult:
    run_id = f"{strategy}:{dataset}"
    result_ids = {
        "s1": UUID("11111111-1111-1111-1111-111111111111"),
        "s2": UUID("22222222-2222-2222-2222-222222222222"),
        "s3": UUID("33333333-3333-3333-3333-333333333333"),
    }
    result_id = result_ids[strategy]
    return ResearchResult(
        spec=_spec(
            run_id,
            dataset,
            simulation_profile=simulation_profile,
            strategy_id=strategy if structured_strategy else None,
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        time_range_start="2026-01-01T00:00:00+00:00",
        time_range_end="2026-01-01T00:01:00+00:00",
        metrics=metrics,
        result_id=result_id,
    )


def test_experiment_is_logical_metadata_only() -> None:
    experiment = Experiment(name="x")
    assert experiment.name == "x"
    assert not hasattr(experiment, "strategy_id")
    assert not hasattr(experiment, "strategy_version")
    assert not hasattr(experiment, "parameters")


def test_experiment_requires_name() -> None:
    with pytest.raises(ValueError, match="experiment name"):
        Experiment(name="   ")


def test_register_experiment_rejects_duplicate_identity() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="x")
    manager.register_experiment(experiment)

    with pytest.raises(ValueError, match="experiment already registered"):
        manager.register_experiment(experiment)


def test_attach_run_requires_registered_experiment() -> None:
    manager = ExperimentManager()
    experiment_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    with pytest.raises(KeyError, match="experiment not found"):
        manager.attach_run(experiment_id, "run-1")


def test_attach_run_rejects_empty_run_id() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="x")
    manager.register_experiment(experiment)

    with pytest.raises(ValueError, match="run_id"):
        manager.attach_run(experiment.experiment_id, "   ")


def test_attach_run_is_one_to_many_from_experiment() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="x")
    manager.register_experiment(experiment)

    assert manager.attach_run(experiment.experiment_id, "run-2") == "run-2"
    assert manager.attach_run(experiment.experiment_id, "run-1") == "run-1"
    assert manager.runs_for_experiment(experiment.experiment_id) == ("run-1", "run-2")
    assert manager.experiment_for_run("run-1") == experiment.experiment_id
    assert manager.experiment_for_run("run-2") == experiment.experiment_id


def test_attach_run_rejects_duplicate_membership() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="x")
    manager.register_experiment(experiment)
    manager.attach_run(experiment.experiment_id, "run-1")

    with pytest.raises(ValueError, match="already attached to experiment"):
        manager.attach_run(experiment.experiment_id, "run-1")


def test_attach_run_rejects_membership_in_multiple_experiments() -> None:
    manager = ExperimentManager()
    first = Experiment(name="first")
    second = Experiment(name="second")
    manager.register_experiment(first)
    manager.register_experiment(second)
    manager.attach_run(first.experiment_id, "run-1")

    with pytest.raises(ValueError, match="another experiment"):
        manager.attach_run(second.experiment_id, "run-1")

    assert manager.experiment_for_run("run-1") == first.experiment_id
    assert manager.runs_for_experiment(second.experiment_id) == ()


def test_experiment_accepts_runs_with_different_configurations() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="parameter sweep")
    manager.register_experiment(experiment)

    first = _result(
        "a",
        "s1",
        (("pnl", Decimal("10")),),
        simulation_profile="REALISTIC",
        structured_strategy=True,
    )
    second = _result(
        "a",
        "s2",
        (("pnl", Decimal("12")),),
        simulation_profile="CONSERVATIVE",
        structured_strategy=True,
    )

    manager.attach_run(experiment.experiment_id, first.spec.run_id)
    manager.attach_run(experiment.experiment_id, second.spec.run_id)
    manager.record_result(first)
    manager.record_result(second)

    assert manager.runs_for_experiment(experiment.experiment_id) == (
        first.spec.run_id,
        second.spec.run_id,
    )
    assert first.spec.strategy_identity() != second.spec.strategy_identity()
    assert first.fingerprint != second.fingerprint
    assert manager.get_result(first.result_id) is first
    assert manager.get_result(second.result_id) is second


def test_experiment_run_membership_does_not_duplicate_result_or_configuration() -> None:
    manager = ExperimentManager()
    experiment = Experiment(name="x")
    manager.register_experiment(experiment)
    result = _result("a", "s1", (("pnl", Decimal("10")),))

    manager.attach_run(experiment.experiment_id, result.spec.run_id)
    manager.record_result(result)

    assert manager.runs_for_experiment(experiment.experiment_id) == (result.spec.run_id,)
    assert manager.get_result(result.result_id) is result
    assert len(manager.experiments()) == 1
    assert len(manager.results()) == 1


def test_compare_experiments_reports_metric_delta() -> None:
    manager = ExperimentManager()
    left = _result("a", "s1", (("pnl", Decimal("10")),))
    right = _result("a", "s2", (("pnl", Decimal("14")),))
    comparison = manager.compare(left, right)
    assert comparison.comparable is True
    assert comparison.same_dataset is True
    assert comparison.metric_deltas == (("pnl", Decimal("4")),)


def test_compare_flags_dataset_difference() -> None:
    manager = ExperimentManager()
    left = _result("a", "s1", (("pnl", Decimal("10")),))
    right = _result("b", "s2", (("pnl", Decimal("14")),))
    comparison = manager.compare(left, right)
    assert comparison.comparable is False
    assert comparison.same_dataset is False
    assert "dataset or dataset version differs" in comparison.reasons


def test_compare_allows_provenance_difference_on_same_dataset() -> None:
    manager = ExperimentManager()
    left = _result("a", "s1", (("pnl", Decimal("10")),))
    right = _result("a", "s2", (("pnl", Decimal("14")),), simulation_profile="OTHER")
    comparison = manager.compare(left, right)
    assert comparison.comparable is True
    assert comparison.same_dataset is True
    assert comparison.same_provenance is False
    assert comparison.reasons == ()


def test_compare_rejects_blocked_results() -> None:
    manager = ExperimentManager()
    complete = _result("a", "s1", (("pnl", Decimal("10")),))
    blocked = ResearchResult(
        spec=complete.spec,
        quality=ResultQuality.BLOCKED,
        started_at=complete.started_at,
        completed_at=complete.completed_at,
        time_range_start=complete.time_range_start,
        time_range_end=complete.time_range_end,
        metrics=complete.metrics,
        limitations=("data unavailable",),
        result_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    comparison = manager.compare(complete, blocked)
    assert comparison.comparable is False
    assert "one or more results are BLOCKED" in comparison.reasons
