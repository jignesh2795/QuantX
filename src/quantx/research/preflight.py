"""Preflight checks that must pass before a research run is executed."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .artifacts import ResearchArtifactManifest
from .integrity import ArtifactIntegrity, IntegrityStatus, verify_artifact


class PreflightStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PreflightItem:
    artifact_id: str
    status: IntegrityStatus
    message: str


@dataclass(frozen=True, slots=True)
class ResearchPreflightResult:
    status: PreflightStatus
    items: tuple[PreflightItem, ...]

    @property
    def is_ready(self) -> bool:
        return self.status is PreflightStatus.READY


class ResearchPreflightGate:
    """Block a research run when required local artifacts fail integrity checks."""

    def check(self, manifest: ResearchArtifactManifest) -> ResearchPreflightResult:
        items: list[PreflightItem] = []
        blocked = False
        for artifact in manifest.artifacts:
            if not artifact.uri.startswith("file://"):
                items.append(
                    PreflightItem(
                        artifact.artifact_id,
                        IntegrityStatus.UNSUPPORTED_URI,
                        "artifact URI cannot be verified locally",
                    )
                )
                blocked = True
                continue
            path = Path(artifact.uri.removeprefix("file://"))
            result: ArtifactIntegrity = verify_artifact(path, artifact.content_hash)
            items.append(
                PreflightItem(artifact.artifact_id, result.status, result.message)
            )
            if result.status is not IntegrityStatus.VERIFIED:
                blocked = True

        status = PreflightStatus.BLOCKED if blocked else PreflightStatus.READY
        return ResearchPreflightResult(status, tuple(items))

    def require_ready(self, manifest: ResearchArtifactManifest) -> ResearchPreflightResult:
        result = self.check(manifest)
        if not result.is_ready:
            raise RuntimeError("research preflight blocked: one or more artifacts failed integrity verification")
        return result
