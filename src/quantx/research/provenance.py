"""Canonical provenance records and deterministic fingerprints for research runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    """Immutable inputs that define the reproducibility identity of a run."""

    dataset_id: str
    dataset_version: str
    instrument_master_version: str
    market_rule_version: str
    execution_model_version: str
    simulation_profile: str
    code_revision: str
    configuration_revision: str
    random_seed: int | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "instrument_master_version": self.instrument_master_version,
            "market_rule_version": self.market_rule_version,
            "execution_model_version": self.execution_model_version,
            "simulation_profile": self.simulation_profile,
            "code_revision": self.code_revision,
            "configuration_revision": self.configuration_revision,
            "random_seed": self.random_seed,
            "extra": dict(sorted(self.extra.items())),
        }

    def fingerprint(self) -> str:
        """Return a stable SHA-256 fingerprint of canonical provenance."""
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
