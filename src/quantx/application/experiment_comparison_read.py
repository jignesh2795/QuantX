"""Read-side comparison of durable research run results."""

from __future__ import annotations

from uuid import UUID

from quantx.research.experiments import ExperimentComparison, ExperimentManager

from .research_run_read import ResearchRunReadService


class ExperimentComparisonReadService:
    """Compare persisted research results without duplicating comparison semantics."""

    def __init__(self, *, run_read_service: ResearchRunReadService) -> None:
        self._run_read_service = run_read_service

    def compare_runs(self, left_run_id: str, right_run_id: str) -> ExperimentComparison:
        """Compare two completed persisted research runs."""
        if not left_run_id.strip():
            raise ValueError("left_run_id must not be empty")
        if not right_run_id.strip():
            raise ValueError("right_run_id must not be empty")

        left_snapshot = self._run_read_service.get(left_run_id)
        if left_snapshot is None:
            raise ValueError(f"left research run not found: {left_run_id}")
        if left_snapshot.result is None:
            raise ValueError(f"left research run has no persisted result: {left_run_id}")

        right_snapshot = self._run_read_service.get(right_run_id)
        if right_snapshot is None:
            raise ValueError(f"right research run not found: {right_run_id}")
        if right_snapshot.result is None:
            raise ValueError(f"right research run has no persisted result: {right_run_id}")

        return ExperimentManager().compare(left_snapshot.result, right_snapshot.result)


__all__ = ["ExperimentComparisonReadService"]
