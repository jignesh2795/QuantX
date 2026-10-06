from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.research_run import ResearchRunApplicationService
from quantx.domain.clock import FixedClock
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunState
from quantx.research.storage import InMemoryResearchRunRepository


def _spec() -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id="run-1",
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


def test_research_run_application_service_completes_durable_lifecycle() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)
    spec = _spec()
    result = _result(spec)
    calls: list[str] = []

    execution = service.execute(
        spec,
        lambda: calls.append("executed") or result,
    )

    assert calls == ["executed"]
    assert execution.result is result
    assert execution.run.state is ResearchRunState.COMPLETED
    assert execution.run.run_id == spec.run_id
    assert execution.run.provenance_fingerprint == result.fingerprint

    stored = repository.get_run(spec.run_id)
    assert stored == execution.run
    assert stored is not None


def test_research_run_application_service_persists_failed_lifecycle_and_reraises() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)

    with pytest.raises(RuntimeError, match="backtest failed"):
        service.execute(
            _spec(),
            lambda: (_ for _ in ()).throw(RuntimeError("backtest failed")),
        )

    stored = repository.get_run("run-1")
    assert stored is not None
    assert stored.state is ResearchRunState.FAILED
    assert stored.result_id is None
    assert stored.failure_reason == "RuntimeError: backtest failed"


def test_research_run_application_service_rejects_naive_clock() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0))
    service = ResearchRunApplicationService(repository=repository, clock=clock)

    with pytest.raises(ValueError, match="timezone-aware"):
        service.execute(_spec(), lambda: _result(_spec()))

    assert repository.get_run("run-1") is None
