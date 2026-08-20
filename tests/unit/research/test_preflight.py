from __future__ import annotations

from pathlib import Path

import pytest

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.preflight import PreflightStatus, ResearchPreflightGate
from quantx.research.integrity import sha256_file


def _manifest(path: Path, expected_hash: str | None = None) -> ResearchArtifactManifest:
    digest = expected_hash or sha256_file(path)
    return ResearchArtifactManifest(
        run_fingerprint="run-fp-1",
        artifacts=(
            ResearchArtifact(
                artifact_id="dataset-1",
                artifact_type="dataset",
                content_hash=digest,
                uri=f"file://{path}",
            ),
        ),
    )


def test_preflight_ready_for_verified_artifact(tmp_path: Path) -> None:
    path = tmp_path / "dataset.csv"
    path.write_text("timestamp,price\n2026-01-01T00:00:00Z,100\n", encoding="utf-8")

    result = ResearchPreflightGate().check(_manifest(path))

    assert result.status is PreflightStatus.READY
    assert result.is_ready is True


def test_preflight_blocks_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "dataset.csv"
    path.write_text("original", encoding="utf-8")
    manifest = _manifest(path, expected_hash="0" * 64)

    result = ResearchPreflightGate().check(manifest)

    assert result.status is PreflightStatus.BLOCKED
    assert result.is_ready is False


def test_preflight_blocks_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    manifest = _manifest(path, expected_hash="0" * 64)

    result = ResearchPreflightGate().check(manifest)

    assert result.status is PreflightStatus.BLOCKED


def test_require_ready_raises_when_blocked(tmp_path: Path) -> None:
    path = tmp_path / "dataset.csv"
    path.write_text("changed", encoding="utf-8")
    manifest = _manifest(path, expected_hash="0" * 64)

    with pytest.raises(RuntimeError, match="research preflight blocked"):
        ResearchPreflightGate().require_ready(manifest)


def test_preflight_blocks_unsupported_uri() -> None:
    manifest = ResearchArtifactManifest(
        run_fingerprint="run-fp-1",
        artifacts=(
            ResearchArtifact(
                artifact_id="remote-1",
                artifact_type="dataset",
                content_hash="0" * 64,
                uri="https://example.com/data.csv",
            ),
        ),
    )

    result = ResearchPreflightGate().check(manifest)

    assert result.status is PreflightStatus.BLOCKED
