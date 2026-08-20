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
