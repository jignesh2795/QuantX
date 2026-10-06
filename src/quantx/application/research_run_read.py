"""Read-side rehydration of durable research runs and their bound results."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from quantx.research.result import ResearchResult
from quantx.research.run import ResearchRunRecord, ResearchRunState
from quantx.research.storage import ResearchRunRepository, ResearchStore


@dataclass(frozen=True, slots=True)
class ResearchRunSnapshot:
    """Persisted research run plus its bound result when one exists."""

    run: ResearchRunRecord
    result: ResearchResult | None

    def __post_init__(self) -> None:
        if self.run.state is ResearchRunState.COMPLETED:
            if self.run.result_id is None:
                raise ValueError("COMPLETED research run requires result_id")
            if self.result is None:
                raise ValueError("COMPLETED research run requires a persisted result")
            if self.result.result_id != self.run.result_id:
                raise ValueError("research result_id does not match research run")
            if self.result.spec.run_id != self.run.run_id:
                raise ValueError("research result run_id does not match research run")
            if self.result.fingerprint != self.run.provenance_fingerprint:
                raise ValueError(
                    "research result provenance fingerprint does not match research run"
                )
        elif self.result is not None:
            raise ValueError("non-COMPLETED research run cannot expose a result")


class ResearchRunReadService:
    """Rehydrate a research run from its durable run and result boundaries."""

    def __init__(
        self,
        *,
        run_repository: ResearchRunRepository,
        result_store: ResearchStore,
    ) -> None:
        self._run_repository = run_repository
        self._result_store = result_store

    def get(self, run_id: str) -> ResearchRunSnapshot | None:
        """Return a validated persisted run snapshot, or None when absent."""
        if not run_id.strip():
            raise ValueError("run_id must not be empty")

        run = self._run_repository.get_run(run_id)
        if run is None:
            return None

        result = (
            self._result_store.get_result(run.result_id)
            if run.state is ResearchRunState.COMPLETED and run.result_id is not None
            else None
        )
        return ResearchRunSnapshot(run=run, result=result)

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        """Return a persisted result through the existing research read boundary."""
        return self._result_store.get_result(result_id)


__all__ = ["ResearchRunReadService", "ResearchRunSnapshot"]
