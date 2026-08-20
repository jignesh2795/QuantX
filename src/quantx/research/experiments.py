"""Experiment management for reproducible research runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from .result import ResearchResult


@dataclass(frozen=True, slots=True)
class Experiment:
    """Immutable definition of a reproducible research experiment."""

    experiment_id: UUID = field(default_factory=uuid4)
    name: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    parameters: tuple[tuple[str, str], ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name must not be empty")
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version must not be empty")


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    """Explicit comparison between two persisted research results."""

    left_result_id: UUID
    right_result_id: UUID
    metric_deltas: tuple[tuple[str, Decimal], ...]
    same_dataset: bool
    same_strategy_version: bool
    comparable: bool
    reasons: tuple[str, ...] = ()


class ExperimentManager:
    """In-memory experiment/result registry; persistence is an infrastructure concern."""

    def __init__(self) -> None:
        self._experiments: dict[UUID, Experiment] = {}
        self._results: dict[UUID, ResearchResult] = {}

    def register_experiment(self, experiment: Experiment) -> Experiment:
        if experiment.experiment_id in self._experiments:
            raise ValueError("experiment already registered")
        self._experiments[experiment.experiment_id] = experiment
        return experiment

    def record_result(self, result: ResearchResult) -> ResearchResult:
        if result.result_id in self._results:
            raise ValueError("research result already registered")
        self._results[result.result_id] = result
        return result

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        return self._results.get(result_id)

    def compare(self, left: ResearchResult, right: ResearchResult) -> ExperimentComparison:
        reasons: list[str] = []
        same_dataset = left.provenance.dataset_id == right.provenance.dataset_id
        same_strategy = left.provenance.strategy_version == right.provenance.strategy_version
        if not same_dataset:
            reasons.append("dataset differs")
        if not same_strategy:
            reasons.append("strategy version differs")
        comparable = not left.is_blocked and not right.is_blocked
        if not comparable:
            reasons.append("one or more results are BLOCKED")
        left_metrics = dict(left.metrics)
        right_metrics = dict(right.metrics)
        shared = set(left_metrics) & set(right_metrics)
        deltas = tuple((key, right_metrics[key] - left_metrics[key]) for key in sorted(shared))
        return ExperimentComparison(
            left.result_id,
            right.result_id,
            deltas,
            same_dataset,
            same_strategy,
            comparable,
            tuple(reasons),
        )

    def experiments(self) -> tuple[Experiment, ...]:
        return tuple(self._experiments.values())

    def results(self) -> tuple[ResearchResult, ...]:
        return tuple(self._results.values())
