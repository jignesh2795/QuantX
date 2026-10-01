"""Immutable research-run/result provenance records."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from .provenance import ResearchProvenance


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

    def to_provenance(self) -> ResearchProvenance:
        return ResearchProvenance(
            dataset_id=self.dataset_id,
            dataset_version=self.dataset_version,
            instrument_master_version=self.instrument_master_version,
            market_rule_version=self.market_rule_version,
            execution_model_version=self.execution_model_version,
            simulation_profile=self.simulation_profile,
            code_revision=self.code_revision,
            configuration_revision=self.configuration_revision,
            random_seed=self.random_seed,
            extra={"run_id": self.run_id},
        )


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
    result_id: UUID = field(default_factory=uuid4)
    provenance: ResearchProvenance | None = None

    def __post_init__(self) -> None:
        expected = self.spec.to_provenance()
        if self.provenance is not None and self.provenance.fingerprint() != expected.fingerprint():
            raise ValueError("provenance does not match research run spec")
        if self.quality is ResultQuality.BLOCKED and not self.limitations:
            raise ValueError("BLOCKED results must include limitations")
        if self.provenance is None:
            object.__setattr__(self, "provenance", expected)

    @property
    def is_blocked(self) -> bool:
        return self.quality is ResultQuality.BLOCKED

    def metric(self, name: str) -> Decimal | None:
        for key, value in self.metrics:
            if key == name:
                return value
        return None

    @property
    def reproducibility_key(self) -> tuple[str, ...]:
        return (
            self.provenance.dataset_id,
            self.provenance.dataset_version,
            self.provenance.instrument_master_version,
            self.provenance.market_rule_version,
            self.provenance.execution_model_version,
            self.provenance.simulation_profile,
            self.provenance.code_revision,
            self.provenance.configuration_revision,
            str(self.provenance.random_seed),
        )

    @property
    def fingerprint(self) -> str:
        return self.provenance.fingerprint()
