"""In-memory persistence boundary for research results and artifacts.

The core intentionally exposes a storage protocol so SQLite/Postgres/object
storage can be added later without changing the research domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .artifacts import ResearchArtifactManifest
from .result import ResearchResult


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
        if manifest.manifest_id in self._manifests:
            raise ValueError("research artifact manifest already exists")
        self._manifests[manifest.manifest_id] = manifest

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        return self._manifests.get(manifest_id)
