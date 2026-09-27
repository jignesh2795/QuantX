import pytest

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest


def test_manifest_is_order_independent() -> None:
    first = ResearchArtifact("data", "dataset", "abc", "file:///data")
    second = ResearchArtifact("config", "configuration", "def", "file:///config")
    a = ResearchArtifactManifest("run-hash", (first, second))
    b = ResearchArtifactManifest("run-hash", (second, first))
    assert a.fingerprint() == b.fingerprint()


def test_manifest_changes_when_artifact_hash_changes() -> None:
    first = ResearchArtifact("data", "dataset", "abc", "file:///data")
    changed = ResearchArtifact("data", "dataset", "xyz", "file:///data")
    assert ResearchArtifactManifest("run-hash", (first,)).fingerprint() != ResearchArtifactManifest("run-hash", (changed,)).fingerprint()


def test_manifest_rejects_duplicate_artifact_ids() -> None:
    first = ResearchArtifact("data", "dataset", "abc", "file:///data")
    duplicate = ResearchArtifact("data", "dataset", "def", "file:///other")
    with pytest.raises(ValueError, match="duplicate artifact_id"):
        ResearchArtifactManifest("run-hash", (first, duplicate))


def test_manifest_requires_identity_fields() -> None:
    artifact = ResearchArtifact("data", "dataset", "abc", "file:///data")
    with pytest.raises(ValueError, match="run_fingerprint must not be empty"):
        ResearchArtifactManifest("  ", (artifact,))
    with pytest.raises(ValueError, match="manifest_version must not be empty"):
        ResearchArtifactManifest("run-hash", (artifact,), manifest_version=" ")
