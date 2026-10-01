"""Persistence boundaries for research results and provenance manifests."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .artifacts import ResearchArtifact, ResearchArtifactManifest
from .provenance import ResearchProvenance
from .result import ResearchResult, ResearchRunSpec, ResultQuality


class ResearchStore(Protocol):
    def save_result(self, result: ResearchResult) -> None: ...
    def get_result(self, result_id: UUID) -> ResearchResult | None: ...
    def save_manifest(self, manifest: ResearchArtifactManifest) -> None: ...
    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None: ...


@dataclass(slots=True)
class InMemoryResearchStore:
    """Deterministic test/dev implementation of the persistence boundary."""

    _results: dict[UUID, ResearchResult]
    _manifests: dict[str, ResearchArtifactManifest]

    def __init__(self) -> None:
        self._results = {}
        self._manifests = {}

    def save_result(self, result: ResearchResult) -> None:
        if result.result_id in self._results:
            raise ValueError("research result already exists")
        self._results[result.result_id] = result

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        return self._results.get(result_id)

    def save_manifest(self, manifest: ResearchArtifactManifest) -> None:
        manifest_id = manifest.fingerprint()
        if manifest_id in self._manifests:
            raise ValueError("research artifact manifest already exists")
        self._manifests[manifest_id] = manifest

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        return self._manifests.get(manifest_id)


class LocalFilesystemResearchStore:
    """Content-addressed local persistence for research metadata.

    Only metadata is persisted here; artifact payloads remain at the URIs in
    their manifests. Writes are atomic via temporary files and ``replace``.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._results_dir = self._root / "results"
        self._manifests_dir = self._root / "manifests"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: ResearchResult) -> None:
        path = self._results_dir / f"{result.result_id}.json"
        if path.exists():
            raise ValueError("research result already exists")
        self._atomic_write(path, self._result_payload(result))

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        path = self._results_dir / f"{result_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return self._result_from_payload(payload)

    def save_manifest(self, manifest: ResearchArtifactManifest) -> None:
        manifest_id = manifest.fingerprint()
        path = self._manifests_dir / f"{manifest_id}.json"
        if path.exists():
            raise ValueError("research artifact manifest already exists")
        self._atomic_write(path, manifest.canonical_payload())

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        path = self._manifests_dir / f"{manifest_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ResearchArtifactManifest(
            run_fingerprint=payload["run_fingerprint"],
            manifest_version=payload["manifest_version"],
            artifacts=tuple(
                ResearchArtifact(
                    artifact_id=item["artifact_id"],
                    artifact_type=item["artifact_type"],
                    content_hash=item["content_hash"],
                    uri=item["uri"],
                    size_bytes=item.get("size_bytes"),
                    metadata=item.get("metadata", {}),
                )
                for item in payload["artifacts"]
            ),
        )

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, object]) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        temp.replace(path)

    @staticmethod
    def _result_payload(result: ResearchResult) -> dict[str, object]:
        provenance = result.provenance
        assert provenance is not None
        return {
            "result_id": str(result.result_id),
            "spec": {
                "run_id": result.spec.run_id,
                "dataset_id": result.spec.dataset_id,
                "dataset_version": result.spec.dataset_version,
                "instrument_master_version": result.spec.instrument_master_version,
                "market_rule_version": result.spec.market_rule_version,
                "execution_model_version": result.spec.execution_model_version,
                "simulation_profile": result.spec.simulation_profile,
                "code_revision": result.spec.code_revision,
                "configuration_revision": result.spec.configuration_revision,
                "random_seed": result.spec.random_seed,
            },
            "quality": result.quality.value,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "time_range_start": result.time_range_start,
            "time_range_end": result.time_range_end,
            "metrics": [[key, str(value)] for key, value in result.metrics],
            "assumptions": list(result.assumptions),
            "limitations": list(result.limitations),
            "provenance": provenance.canonical_payload(),
        }

    @staticmethod
    def _result_from_payload(payload: dict[str, object]) -> ResearchResult:
        spec_payload = payload["spec"]
        spec = ResearchRunSpec(**spec_payload)
        provenance_payload = payload["provenance"]
        provenance = ResearchProvenance(
            dataset_id=provenance_payload["dataset_id"],
            dataset_version=provenance_payload["dataset_version"],
            instrument_master_version=provenance_payload["instrument_master_version"],
            market_rule_version=provenance_payload["market_rule_version"],
            execution_model_version=provenance_payload["execution_model_version"],
            simulation_profile=provenance_payload["simulation_profile"],
            code_revision=provenance_payload["code_revision"],
            configuration_revision=provenance_payload["configuration_revision"],
            random_seed=provenance_payload.get("random_seed"),
            extra=provenance_payload.get("extra", {}),
        )
        return ResearchResult(
            spec=spec,
            quality=ResultQuality(payload["quality"]),
            started_at=payload["started_at"],
            completed_at=payload["completed_at"],
            time_range_start=payload["time_range_start"],
            time_range_end=payload["time_range_end"],
            metrics=tuple((key, Decimal(value)) for key, value in payload["metrics"]),
            assumptions=tuple(payload["assumptions"]),
            limitations=tuple(payload["limitations"]),
            result_id=UUID(payload["result_id"]),
            provenance=provenance,
        )
