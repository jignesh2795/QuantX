"""Immutable manifests for research artifacts and provenance-linked outputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    """A content-addressed artifact referenced by a research run."""

    artifact_id: str
    artifact_type: str
    content_hash: str
    uri: str
    size_bytes: int | None = None
    metadata: Mapping[str, str] = None

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be empty")
        if not self.artifact_type.strip():
            raise ValueError("artifact_type must not be empty")
        if not self.content_hash.strip():
            raise ValueError("content_hash must not be empty")
        if not self.uri.strip():
            raise ValueError("uri must not be empty")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


@dataclass(frozen=True, slots=True)
class ResearchArtifactManifest:
    """Canonical manifest linking a run to immutable research artifacts."""

    run_fingerprint: str
    artifacts: tuple[ResearchArtifact, ...] = ()
    manifest_version: str = "1"

    def canonical_payload(self) -> dict[str, object]:
        ordered = sorted(self.artifacts, key=lambda item: (item.artifact_type, item.artifact_id))
        return {
            "manifest_version": self.manifest_version,
            "run_fingerprint": self.run_fingerprint,
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "artifact_type": item.artifact_type,
                    "content_hash": item.content_hash,
                    "uri": item.uri,
                    "size_bytes": item.size_bytes,
                    "metadata": dict(sorted(item.metadata.items())),
                }
                for item in ordered
            ],
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
