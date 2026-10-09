"""Preflight checks that must pass before a research run is executed."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .artifacts import ResearchArtifactManifest
from .integrity import ArtifactIntegrityVerifier


class PreflightStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PreflightItem:
    artifact_id: str
    status: str
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

    def __init__(self, verifier: ArtifactIntegrityVerifier | None = None) -> None:
        self._verifier = verifier or ArtifactIntegrityVerifier()

    def check(self, manifest: ResearchArtifactManifest) -> ResearchPreflightResult:
        items: list[PreflightItem] = []
        blocked = False
        for artifact in manifest.artifacts:
            result = self._verifier.verify(artifact)
            status = "VERIFIED" if result.verified else "FAILED"
            items.append(PreflightItem(artifact.artifact_id, status, result.reason))
            if not result.verified:
                blocked = True

        status = PreflightStatus.BLOCKED if blocked else PreflightStatus.READY
        return ResearchPreflightResult(status, tuple(items))

    def require_ready(self, manifest: ResearchArtifactManifest) -> ResearchPreflightResult:
        result = self.check(manifest)
        if not result.is_ready:
            raise RuntimeError(
                "research preflight blocked: one or more artifacts failed integrity verification"
            )
        return result
