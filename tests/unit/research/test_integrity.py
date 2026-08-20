from __future__ import annotations

import hashlib

import pytest

from quantx.research.artifacts import ResearchArtifact
from quantx.research.integrity import ArtifactIntegrityError, ArtifactIntegrityVerifier


def test_local_artifact_hash_verifies(tmp_path) -> None:
    path = tmp_path / "dataset.bin"
    path.write_bytes(b"quantx-data")
    digest = hashlib.sha256(b"quantx-data").hexdigest()
    artifact = ResearchArtifact("a1", "dataset", digest, str(path))

    result = ArtifactIntegrityVerifier().verify(artifact)

    assert result.verified is True
    assert result.actual_hash == digest


def test_hash_mismatch_fails_without_repair(tmp_path) -> None:
    path = tmp_path / "dataset.bin"
    path.write_bytes(b"changed")
    artifact = ResearchArtifact("a1", "dataset", "0" * 64, str(path))

    result = ArtifactIntegrityVerifier().verify(artifact)

    assert result.verified is False
    assert result.reason == "content hash mismatch"
    with pytest.raises(ArtifactIntegrityError):
        ArtifactIntegrityVerifier().require_verified(artifact)


def test_missing_artifact_is_not_fabricated(tmp_path) -> None:
    path = tmp_path / "missing.bin"
    artifact = ResearchArtifact("a1", "dataset", "0" * 64, str(path))

    result = ArtifactIntegrityVerifier().verify(artifact)

    assert result.verified is False
    assert result.actual_hash is None
    assert result.reason == "artifact file is unavailable"


def test_unsupported_remote_uri_is_not_downloaded() -> None:
    artifact = ResearchArtifact("a1", "dataset", "0" * 64, "https://example.invalid/data")

    result = ArtifactIntegrityVerifier().verify(artifact)

    assert result.verified is False
    assert result.reason == "artifact URI is not a supported local file URI"
