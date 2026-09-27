from decimal import Decimal
from uuid import UUID

import pytest

from quantx.research.experiments import Experiment, ExperimentManager
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality


def _spec(run_id: str, dataset: str) -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id=run_id,
        dataset_id=dataset,
        dataset_version="v1",
        instrument_master_version="instruments-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg1",
    )


def _result(dataset: str, strategy: str, metrics: tuple[tuple[str, Decimal], ...]) -> ResearchResult:
    run_id = f"{strategy}:{dataset}"
    result_id = (
        UUID("11111111-1111-1111-1111-111111111111")
        if dataset == "a"
        else UUID("22222222-2222-2222-2222-222222222222")
    )
    return ResearchResult(
        spec=_spec(run_id, dataset),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        time_range_start="2026-01-01T00:00:00+00:00",
        time_range_end="2026-01-01T00:01:00+00:00",
        metrics=metrics,
        result_id=result_id,
    )


def test_experiment_requires_strategy_identity() -> None:
    with pytest.raises(ValueError):
        Experiment(name="x", strategy_id="", strategy_version="v1")


def test_compare_experiments_reports_metric_delta() -> None:
    manager = ExperimentManager()
    left = _result("a", "s1", (("pnl", Decimal("10")),))
    right = _result("a", "s1", (("pnl", Decimal("14")),))
    comparison = manager.compare(left, right)
    assert comparison.comparable is True
    assert comparison.same_dataset is True
    assert comparison.metric_deltas == (("pnl", Decimal("4")),)


def test_compare_flags_dataset_difference() -> None:
    manager = ExperimentManager()
    left = _result("a", "s1", (("pnl", Decimal("10")),))
    right = _result("b", "s1", (("pnl", Decimal("14")),))
    comparison = manager.compare(left, right)
    assert comparison.comparable is True
    assert comparison.same_dataset is False
    assert "dataset or dataset version differs" in comparison.reasons
