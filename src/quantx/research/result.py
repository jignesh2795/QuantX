"""Immutable research-run/result provenance records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ResultQuality(StrEnum):
    COMPLETE_OBSERVED = "COMPLETE_OBSERVED"
    COMPLETE_WITH_DETERMINISTIC_DERIVATIONS = "COMPLETE_WITH_DETERMINISTIC_DERIVATIONS"
    MODEL_ESTIMATED = "MODEL_ESTIMATED"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ResearchRunSpec:
    run_id: str
    dataset_id: str
    dataset_version: str
    instrument_master_version: str
    market_rule_version: str
    execution_model_version: str
    simulation_profile: str
    code_revision: str
    configuration_revision: str
    random_seed: int | None = None


@dataclass(frozen=True, slots=True)
class ResearchResult:
    spec: ResearchRunSpec
    quality: ResultQuality
    started_at: str
    completed_at: str
    time_range_start: str
    time_range_end: str
    metrics: tuple[tuple[str, Decimal], ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def metric(self, name: str) -> Decimal | None:
        for key, value in self.metrics:
            if key == name:
                return value
        return None

    @property
    def reproducibility_key(self) -> tuple[str, ...]:
        return (
            self.spec.dataset_id,
            self.spec.dataset_version,
            self.spec.instrument_master_version,
            self.spec.market_rule_version,
            self.spec.execution_model_version,
            self.spec.simulation_profile,
            self.spec.code_revision,
            self.spec.configuration_revision,
            str(self.spec.random_seed),
        )
