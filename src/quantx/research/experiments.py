"""Experiment management for reproducible research runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from .result import ResearchResult


@dataclass(frozen=True, slots=True)
class Experiment:
    """Immutable logical grouping of research execution instances."""

    experiment_id: UUID = field(default_factory=uuid4)
    name: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name must not be empty")


class ExperimentRepository(Protocol):
    """Database-neutral persistence contract for experiment catalog state."""

    def create_experiment(self, experiment: Experiment) -> Experiment: ...

    def get_experiment(self, experiment_id: UUID) -> Experiment | None: ...

    def experiments(self) -> tuple[Experiment, ...]: ...

    def attach_run(self, experiment_id: UUID, run_id: str) -> str: ...

    def experiment_for_run(self, run_id: str) -> UUID | None: ...

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    """Explicit comparison between two persisted research results."""

    left_result_id: UUID
    right_result_id: UUID
    metric_deltas: tuple[tuple[str, Decimal], ...]
    same_dataset: bool
    same_strategy_version: bool
    same_provenance: bool
    comparable: bool
    reasons: tuple[str, ...] = ()


class ExperimentManager:
    """In-memory experiment/result registry; persistence is an infrastructure concern."""

    def __init__(self) -> None:
        self._experiments: dict[UUID, Experiment] = {}
        self._results: dict[UUID, ResearchResult] = {}
        self._run_experiments: dict[str, UUID] = {}

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

    def attach_run(self, experiment_id: UUID, run_id: str) -> str:
        """Bind one research execution instance to one logical experiment."""
        if experiment_id not in self._experiments:
            raise KeyError(f"experiment not found: {experiment_id}")
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        existing_experiment_id = self._run_experiments.get(run_id)
        if existing_experiment_id is not None:
            if existing_experiment_id == experiment_id:
                raise ValueError("research run already attached to experiment")
            raise ValueError("research run already attached to another experiment")
        self._run_experiments[run_id] = experiment_id
        return run_id

    def experiment_for_run(self, run_id: str) -> UUID | None:
        """Return the logical experiment owning a run, if it is attached."""
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        return self._run_experiments.get(run_id)

    def runs_for_experiment(self, experiment_id: UUID) -> tuple[str, ...]:
        """Return attached run identities in deterministic order."""
        if experiment_id not in self._experiments:
            raise KeyError(f"experiment not found: {experiment_id}")
        return tuple(
            sorted(
                run_id
                for run_id, attached_experiment_id in self._run_experiments.items()
                if attached_experiment_id == experiment_id
            )
        )

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        return self._results.get(result_id)

    def compare(self, left: ResearchResult, right: ResearchResult) -> ExperimentComparison:
        reasons: list[str] = []
        left_provenance = left.provenance
        right_provenance = right.provenance
        if left_provenance is None or right_provenance is None:
            raise ValueError("research result provenance is required for comparison")
        same_dataset = (
            left_provenance.dataset_id == right_provenance.dataset_id
            and left_provenance.dataset_version == right_provenance.dataset_version
        )
        left_strategy = left.spec.strategy_identity()
        right_strategy = right.spec.strategy_identity()
        same_strategy = (
            left_strategy is not None
            and right_strategy is not None
            and left_strategy == right_strategy
        )
        same_provenance = left.fingerprint == right.fingerprint
        # Provenance differences are expected when comparing parameter/model
        # variants. Strategy identity is retained as comparison context, while
        # dataset identity and result quality define this conservative boundary.
        comparable = same_dataset and not left.is_blocked and not right.is_blocked
        if not comparable:
            if not same_dataset:
                reasons.append("dataset or dataset version differs")
            if left.is_blocked or right.is_blocked:
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
            same_provenance,
            comparable,
            tuple(reasons),
        )

    def experiments(self) -> tuple[Experiment, ...]:
        return tuple(self._experiments.values())

    def results(self) -> tuple[ResearchResult, ...]:
        return tuple(self._results.values())
