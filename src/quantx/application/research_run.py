"""Application orchestration for durable research-run execution lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from quantx.domain.clock import Clock
from quantx.research.result import ResearchResult, ResearchRunSpec
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import ResearchRunRepository

ResearchOperation = Callable[[], ResearchResult]


@dataclass(frozen=True, slots=True)
class ResearchRunExecution:
    """Successful durable research execution and its terminal run record."""

    run: ResearchRunRecord
    result: ResearchResult

    def __post_init__(self) -> None:
        if self.run.state is not ResearchRunState.COMPLETED:
            raise ValueError("successful research execution requires a COMPLETED run")
        if self.result.spec.run_id != self.run.run_id:
            raise ValueError("research result run_id does not match completed run")
        if self.result.fingerprint != self.run.provenance_fingerprint:
            raise ValueError("research result provenance does not match completed run")
        if self.run.result_id != self.result.result_id:
            raise ValueError("research result_id does not match completed run")


class ResearchRunApplicationService:
    """Coordinate one research execution attempt through durable run lifecycle."""

    def __init__(
        self,
        *,
        repository: ResearchRunRepository,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        spec: ResearchRunSpec,
        operation: ResearchOperation,
    ) -> ResearchRunExecution:
        """Persist CREATED/RUNNING state, execute once, then bind the result atomically."""
        created = ResearchRunRecord(
            run_id=spec.run_id,
            provenance=spec.to_provenance(),
            created_at=self._timestamp(),
        )
        self._repository.create_run(created)
        self._repository.start_run(spec.run_id, self._timestamp())

        try:
            result = operation()
        except Exception as exc:
            try:
                self._repository.fail_run(spec.run_id, f"{type(exc).__name__}: {exc}")
            except Exception as fail_exc:
                raise exc from fail_exc
            raise

        completed = self._repository.complete_run(
            spec.run_id,
            result,
            self._timestamp(),
        )
        return ResearchRunExecution(run=completed, result=result)

    def _timestamp(self) -> str:
        observed = self._clock.now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("research run clock must return a timezone-aware timestamp")
        return observed.isoformat()


__all__ = ["ResearchOperation", "ResearchRunApplicationService", "ResearchRunExecution"]
