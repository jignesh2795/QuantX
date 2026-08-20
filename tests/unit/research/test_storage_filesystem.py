from decimal import Decimal
from pathlib import Path

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import LocalFilesystemResearchStore


def _result() -> ResearchResult:
    return ResearchResult(
        spec=ResearchRunSpec(
            run_id="run-1",
            dataset_id="nse-1m",
            dataset_version="2026-08-20",
            instrument_master_version="v1",
            market_rule_version="v1",
            execution_model_version="paper-core-v0.1",
            simulation_profile="REALISTIC",
            code_revision="abc123",
            configuration_revision="cfg1",
            random_seed=7,
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-08-20T10:00:00Z",
        completed_at="2026-08-20T10:01:00Z",
        time_range_start="2026-08-20T09:00:00Z",
        time_range_end="2026-08-20T10:00:00Z",
        metrics=(("return", Decimal("0.12")),),
    )


def test_filesystem_result_round_trip(tmp_path: Path) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _result()
    store.save_result(result)

    restored = store.get_result(result.result_id)
    assert restored is not None
    assert restored.result_id == result.result_id
    assert restored.metric("return") == Decimal("0.12")
    assert restored.fingerprint == result.fingerprint


def test_filesystem_manifest_uses_content_fingerprint(tmp_path: Path) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    manifest = ResearchArtifactManifest(
        run_fingerprint="run-fingerprint",
        artifacts=(
            ResearchArtifact(
                artifact_id="dataset",
                artifact_type="dataset",
                content_hash="sha256:abc",
                uri="file:///data/dataset.parquet",
            ),
        ),
    )
    store.save_manifest(manifest)

    manifest_id = manifest.fingerprint()
    restored = store.get_manifest(manifest_id)
    assert restored is not None
    assert restored.fingerprint() == manifest_id
