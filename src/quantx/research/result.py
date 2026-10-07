"""Immutable research-run/result provenance records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from .provenance import ResearchProvenance, ResearchRunConfiguration


class ResultQuality(StrEnum):
    COMPLETE_OBSERVED = "COMPLETE_OBSERVED"
    COMPLETE_WITH_DETERMINISTIC_DERIVATIONS = "COMPLETE_WITH_DETERMINISTIC_DERIVATIONS"
    MODEL_ESTIMATED = "MODEL_ESTIMATED"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


def _configuration_identity(
    run_configuration: ResearchRunConfiguration | None,
) -> str:
    """Return a deterministic textual identity for structured run configuration.

    The canonical fingerprint remains the authoritative reproducibility identity;
    this helper only keeps ``reproducibility_key`` total without inventing a
    second hashing layer.
    """
    if run_configuration is None:
        return "unconfigured"
    encoded = json.dumps(
        run_configuration.canonical_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return encoded


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
    run_configuration: ResearchRunConfiguration | None = None

    def to_provenance(self) -> ResearchProvenance:
        """Derive canonical provenance from this spec.

        ``run_id`` identifies a run instance but is deliberately excluded from
        reproducibility identity: two runs of the same configuration share one
        fingerprint. Structured run configuration participates in identity when
        supplied.
        """
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
            run_configuration=self.run_configuration,
        )

    def strategy_identity(self) -> tuple[str, str] | None:
        """Return canonical strategy identity from structured configuration.

        ``None`` when no structured strategy identity is available; callers must
        not infer equivalence from runtime identifiers.
        """
        if self.run_configuration is None:
            return None
        strategy = self.run_configuration.strategy
        if strategy.strategy_id is None or strategy.strategy_version is None:
            return None
        return strategy.strategy_id, strategy.strategy_version


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
        provenance = self.provenance
        if provenance is None:  # pragma: no cover - provenance is always derived
            raise ValueError("research result provenance is required for identity")
        # Structured run configuration participates before random_seed, keeping
        # random_seed as the final element for compatibility.
        return (
            provenance.dataset_id,
            provenance.dataset_version,
            provenance.instrument_master_version,
            provenance.market_rule_version,
            provenance.execution_model_version,
            provenance.simulation_profile,
            provenance.code_revision,
            provenance.configuration_revision,
            _configuration_identity(provenance.run_configuration),
            str(provenance.random_seed),
        )

    @property
    def fingerprint(self) -> str:
        provenance = self.provenance
        if provenance is None:
            raise ValueError("research result provenance is required for fingerprint")
        return provenance.fingerprint()
