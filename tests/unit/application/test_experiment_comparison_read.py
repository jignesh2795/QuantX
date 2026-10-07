"""Application-level tests for durable research result comparison."""

from decimal import Decimal
from uuid import UUID

import pytest

from quantx.application import ExperimentComparisonReadService, ResearchRunReadService
from quantx.research.provenance import ResearchProvenance
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import InMemoryResearchRunRepository, InMemoryResearchStore


def _provenance(*, dataset_id: str = "dataset-1", simulation_profile: str = "REALISTIC") -> ResearchProvenance:
    return ResearchProvenance(
        dataset_id=dataset_id,
        dataset_version="v1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile=simulation_profile,
        code_revision="abc123",
        configuration_revision="cfg1",
    )


def _result(
    run_id: str,
    result_id: UUID,
    *,
    dataset_id: str = "dataset-1",
    simulation_profile: str = "REALISTIC",
    quality: ResultQuality = ResultQuality.COMPLETE_OBSERVED,
    metrics: tuple[tuple[str, Decimal], ...] = (("pnl", Decimal("10")),),
) -> ResearchResult:
    spec = ResearchRunSpec(
        run_id=run_id,
        dataset_id=dataset_id,
        dataset_version="v1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile=simulation_profile,
        code_revision="abc123",
        configuration_revision="cfg1",
    )
    return ResearchResult(
        spec=spec,
        quality=quality,
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        time_range_start="2026-01-01T00:00:00+00:00",
        time_range_end="2026-01-01T00:01:00+00:00",
        metrics=metrics,
        limitations=("data unavailable",) if quality is ResultQuality.BLOCKED else (),
        result_id=result_id,
    )


def _service(
    run_repository: InMemoryResearchRunRepository,
    result_store: InMemoryResearchStore,
) -> ExperimentComparisonReadService:
    return ExperimentComparisonReadService(
        run_read_service=ResearchRunReadService(
            run_repository=run_repository,
            result_store=result_store,
        )
    )


def _persist_completed(
    run_repository: InMemoryResearchRunRepository,
    result_store: InMemoryResearchStore,
    result: ResearchResult,
) -> None:
    run_repository.create_run(
        ResearchRunRecord(
            run_id=result.spec.run_id,
            provenance=_provenance(
                dataset_id=result.spec.dataset_id,
                simulation_profile=result.spec.simulation_profile,
            ),
            created_at=result.started_at,
        )
    )
    result_store.save_result(result)
    run_repository.complete_run(result.spec.run_id, result, result.completed_at)


def test_compare_runs_rehydrates_results_and_reuses_domain_semantics() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    left = _result(
        "run-left",
        UUID("11111111-1111-1111-1111-111111111111"),
        metrics=(("pnl", Decimal("10")), ("trades", Decimal("2"))),
    )
    right = _result(
        "run-right",
        UUID("22222222-2222-2222-2222-222222222222"),
        simulation_profile="CONSERVATIVE",
        metrics=(("pnl", Decimal("14")), ("trades", Decimal("3"))),
    )
    _persist_completed(run_repository, result_store, left)
    _persist_completed(run_repository, result_store, right)

    comparison = _service(run_repository, result_store).compare_runs("run-left", "run-right")

    assert comparison.left_result_id == left.result_id
    assert comparison.right_result_id == right.result_id
    assert comparison.comparable is True
    assert comparison.same_dataset is True
    assert comparison.same_provenance is False
    assert comparison.metric_deltas == (
        ("pnl", Decimal("4")),
        ("trades", Decimal("1")),
    )


def test_compare_runs_fails_closed_for_missing_left_run() -> None:
    service = _service(InMemoryResearchRunRepository(), InMemoryResearchStore())

    with pytest.raises(ValueError, match="left research run not found"):
        service.compare_runs("missing", "run-right")


def test_compare_runs_fails_closed_for_non_completed_run() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    run = ResearchRunRecord(
        run_id="created",
        provenance=_provenance(),
        created_at="2026-01-01T00:00:00Z",
    )
    run_repository.create_run(run)
    service = _service(run_repository, result_store)

    with pytest.raises(ValueError, match="no persisted result"):
        service.compare_runs("created", "created")


def test_compare_runs_preserves_blocked_result_boundary() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    complete = _result(
        "complete",
        UUID("33333333-3333-3333-3333-333333333333"),
        metrics=(("pnl", Decimal("10")),),
    )
    blocked = _result(
        "blocked",
        UUID("44444444-4444-4444-4444-444444444444"),
        quality=ResultQuality.BLOCKED,
        metrics=(("pnl", Decimal("12")),),
    )
    _persist_completed(run_repository, result_store, complete)
    _persist_completed(run_repository, result_store, blocked)

    comparison = _service(run_repository, result_store).compare_runs("complete", "blocked")

    assert comparison.comparable is False
    assert "one or more results are BLOCKED" in comparison.reasons


def test_compare_runs_rejects_blank_run_identity() -> None:
    service = _service(InMemoryResearchRunRepository(), InMemoryResearchStore())

    with pytest.raises(ValueError, match="left_run_id"):
        service.compare_runs("   ", "run-right")

    with pytest.raises(ValueError, match="right_run_id"):
        service.compare_runs("run-left", "   ")


def test_compare_runs_rejects_missing_right_run() -> None:
    run_repository = InMemoryResearchRunRepository()
    result_store = InMemoryResearchStore()
    left = _result(
        "run-left",
        UUID("55555555-5555-5555-5555-555555555555"),
    )
    _persist_completed(run_repository, result_store, left)

    with pytest.raises(ValueError, match="right research run not found"):
        _service(run_repository, result_store).compare_runs("run-left", "missing")
