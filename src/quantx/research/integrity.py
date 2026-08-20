"""Artifact integrity verification for research inputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .artifacts import ResearchArtifact


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact cannot be verified against its manifest hash."""


@dataclass(frozen=True, slots=True)
class ArtifactIntegrityResult:
    artifact_id: str
    expected_hash: str
    actual_hash: str | None
    verified: bool
    reason: str


class ArtifactIntegrityVerifier:
    """Verify local file artifacts without modifying or repairing them."""

    def verify(self, artifact: ResearchArtifact) -> ArtifactIntegrityResult:
        path = self._local_path(artifact.uri)
        if path is None:
            return ArtifactIntegrityResult(
                artifact_id=artifact.artifact_id,
                expected_hash=artifact.content_hash,
                actual_hash=None,
                verified=False,
                reason="artifact URI is not a supported local file URI",
            )
        if not path.exists() or not path.is_file():
            return ArtifactIntegrityResult(
                artifact_id=artifact.artifact_id,
                expected_hash=artifact.content_hash,
                actual_hash=None,
                verified=False,
                reason="artifact file is unavailable",
            )

        actual = self._sha256(path)
        verified = actual == artifact.content_hash
        return ArtifactIntegrityResult(
            artifact_id=artifact.artifact_id,
            expected_hash=artifact.content_hash,
            actual_hash=actual,
            verified=verified,
            reason="verified" if verified else "content hash mismatch",
        )

    def require_verified(self, artifact: ResearchArtifact) -> ArtifactIntegrityResult:
        result = self.verify(artifact)
        if not result.verified:
            raise ArtifactIntegrityError(
                f"artifact {artifact.artifact_id} failed integrity verification: {result.reason}"
            )
        return result

    @staticmethod
    def _local_path(uri: str) -> Path | None:
        if uri.startswith("file://"):
            return Path(uri[7:])
        if "://" in uri:
            return None
        return Path(uri)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
