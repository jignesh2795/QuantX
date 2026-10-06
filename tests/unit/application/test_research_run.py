from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.application.research_run import ResearchRunApplicationService
from quantx.domain.clock import Clock, FixedClock
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunRecord, ResearchRunState
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

    def operation() -> ResearchResult:
        calls.append("executed")
        return result

    execution = service.execute(spec, operation)

    assert calls == ["executed"]
    assert execution.result is result
    assert execution.run.state is ResearchRunState.COMPLETED
    assert execution.run.run_id == spec.run_id
    assert execution.run.provenance_fingerprint == result.fingerprint

    stored = repository.get_run(spec.run_id)
    assert stored is not None
    assert stored == execution.run


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
    class NaiveClock(Clock):
        def now(self) -> datetime:
            return datetime(2026, 10, 6, 10, 0)

    repository = InMemoryResearchRunRepository()
    service = ResearchRunApplicationService(repository=repository, clock=NaiveClock())

    with pytest.raises(ValueError, match="timezone-aware"):
        service.execute(_spec(), lambda: _result(_spec()))

    assert repository.get_run("run-1") is None


class _FaultInjectingRepository(InMemoryResearchRunRepository):
    def __init__(
        self,
        *,
        fail_create: bool = False,
        fail_start: bool = False,
        fail_complete: bool = False,
    ) -> None:
        super().__init__()
        self.fail_create = fail_create
        self.fail_start = fail_start
        self.fail_complete = fail_complete

    def create_run(self, run: ResearchRunRecord) -> ResearchRunRecord:
        if self.fail_create:
            raise RuntimeError("create persistence failed")
        return super().create_run(run)

    def start_run(self, run_id: str, started_at: str) -> ResearchRunRecord:
        if self.fail_start:
            raise RuntimeError("start persistence failed")
        return super().start_run(run_id, started_at)

    def complete_run(
        self,
        run_id: str,
        result: ResearchResult,
        completed_at: str,
    ) -> ResearchRunRecord:
        if self.fail_complete:
            raise RuntimeError("complete persistence failed")
        return super().complete_run(run_id, result, completed_at)


def test_research_run_application_service_does_not_execute_when_create_persistence_fails() -> None:
    repository = _FaultInjectingRepository(fail_create=True)
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)
    calls: list[str] = []

    def operation() -> ResearchResult:
        calls.append("executed")
        return _result(_spec())

    with pytest.raises(RuntimeError, match="create persistence failed"):
        service.execute(_spec(), operation)

    assert calls == []
    assert repository.get_run("run-1") is None


def test_research_run_application_service_leaves_created_when_start_persistence_fails() -> None:
    repository = _FaultInjectingRepository(fail_start=True)
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)

    with pytest.raises(RuntimeError, match="start persistence failed"):
        service.execute(_spec(), lambda: _result(_spec()))

    stored = repository.get_run("run-1")
    assert stored is not None
    assert stored.state is ResearchRunState.CREATED


def test_research_run_application_service_surfaces_completion_persistence_failure() -> None:
    repository = _FaultInjectingRepository(fail_complete=True)
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)

    with pytest.raises(RuntimeError, match="complete persistence failed"):
        service.execute(_spec(), lambda: _result(_spec()))

    stored = repository.get_run("run-1")
    assert stored is not None
    assert stored.state is ResearchRunState.RUNNING
    assert stored.result_id is None


def test_research_run_execution_rejects_mismatched_result_id() -> None:
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    spec = _spec()
    result = _result(spec)

    class WrongResultIdRepository(InMemoryResearchRunRepository):
        def complete_run(
            self,
            run_id: str,
            completed_result: ResearchResult,
            completed_at: str,
        ) -> ResearchRunRecord:
            completed = super().complete_run(run_id, completed_result, completed_at)
            return replace(completed, result_id=uuid4())

    wrong_repository = WrongResultIdRepository()
    wrong_service = ResearchRunApplicationService(repository=wrong_repository, clock=clock)

    with pytest.raises(ValueError, match="result_id"):
        wrong_service.execute(spec, lambda: result)

    stored = wrong_repository.get_run(spec.run_id)
    assert stored is not None
    assert stored.state is ResearchRunState.COMPLETED
