from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.application.research_run import ResearchRunApplicationService
from quantx.application.research_run_read import ResearchRunReadService, ResearchRunSnapshot
from quantx.domain.clock import FixedClock
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import (
    InMemoryResearchRunRepository,
    InMemoryResearchStore,
)


def _spec(run_id: str = "run-1") -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id=run_id,
        dataset_id="dataset-1",
        dataset_version="v1",
        instrument_master_version="instruments-v1",
        market_rule_version="rules-v1",
        execution_model_version="model-v1",
        simulation_profile="paper-v1",
        code_revision="code-v1",
        configuration_revision="config-v1",
        random_seed=7,
    )


def _result(spec: ResearchRunSpec) -> ResearchResult:
    return ResearchResult(
        spec=spec,
        quality=ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS,
        started_at="2026-10-06T10:00:00+00:00",
        completed_at="2026-10-06T10:05:00+00:00",
        time_range_start="2026-01-01T09:15:00+00:00",
        time_range_end="2026-01-01T15:30:00+00:00",
        metrics=(("executed_count", Decimal("2")),),
    )


def _completed(
    run_id: str = "run-1",
) -> tuple[InMemoryResearchRunRepository, InMemoryResearchStore, ResearchResult]:
    repository = InMemoryResearchRunRepository()
    store = InMemoryResearchStore()
    spec = _spec(run_id)
    result = _result(spec)
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    lifecycle = ResearchRunApplicationService(repository=repository, clock=clock)
    lifecycle.execute(spec, lambda: result)
    store.save_result(result)
    return repository, store, result


def test_research_run_read_service_rehydrates_completed_run_and_result() -> None:
    repository, store, result = _completed()
    service = ResearchRunReadService(
        run_repository=repository,
        result_store=store,
    )

    snapshot = service.get("run-1")

    assert snapshot is not None
    assert snapshot.run.state is ResearchRunState.COMPLETED
    assert snapshot.run.result_id == result.result_id
    assert snapshot.result is result


@pytest.mark.parametrize("state", [ResearchRunState.CREATED, ResearchRunState.RUNNING])
def test_research_run_read_service_does_not_load_result_for_non_terminal_run(
    state: ResearchRunState,
) -> None:
    repository = InMemoryResearchRunRepository()
    store = InMemoryResearchStore()
    spec = _spec()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    lifecycle = ResearchRunApplicationService(repository=repository, clock=clock)

    created = lifecycle.execute if state is ResearchRunState.RUNNING else None
    if created is not None:
        repository.create_run(
            ResearchRunRecord(
                run_id="run-1",
                provenance=spec.to_provenance(),
                created_at=clock.now().isoformat(),
            )
        )
        repository.start_run("run-1", clock.now().isoformat())
    else:
        repository.create_run(
            ResearchRunRecord(
                run_id="run-1",
                provenance=spec.to_provenance(),
                created_at=clock.now().isoformat(),
            )
        )

    service = ResearchRunReadService(run_repository=repository, result_store=store)
    snapshot = service.get("run-1")

    assert snapshot is not None
    assert snapshot.run.state is state
    assert snapshot.result is None


def test_research_run_read_service_returns_none_for_missing_run() -> None:
    service = ResearchRunReadService(
        run_repository=InMemoryResearchRunRepository(),
        result_store=InMemoryResearchStore(),
    )

    assert service.get("missing") is None


def test_research_run_read_service_rejects_empty_run_id() -> None:
    service = ResearchRunReadService(
        run_repository=InMemoryResearchRunRepository(),
        result_store=InMemoryResearchStore(),
    )

    with pytest.raises(ValueError, match="run_id"):
        service.get("")


def test_research_run_snapshot_rejects_missing_completed_result() -> None:
    repository, _, _ = _completed()
    run = repository.get_run("run-1")
    assert run is not None

    with pytest.raises(ValueError, match="persisted result"):
        ResearchRunSnapshot(run=run, result=None)


def test_research_run_snapshot_rejects_result_identity_mismatch() -> None:
    repository, _, result = _completed()
    run = repository.get_run("run-1")
    assert run is not None
    wrong_result = ResearchResult(
        spec=result.spec,
        quality=result.quality,
        started_at=result.started_at,
        completed_at=result.completed_at,
        time_range_start=result.time_range_start,
        time_range_end=result.time_range_end,
        metrics=result.metrics,
        assumptions=result.assumptions,
        limitations=result.limitations,
        result_id=uuid4(),
        provenance=result.provenance,
    )

    with pytest.raises(ValueError, match="result_id"):
        ResearchRunSnapshot(run=run, result=wrong_result)
