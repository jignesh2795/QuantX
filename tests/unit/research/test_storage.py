from decimal import Decimal
from uuid import uuid4

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import InMemoryResearchStore, LocalFilesystemResearchStore


def _result() -> ResearchResult:
    return ResearchResult(
        result_id=uuid4(),
        spec=ResearchRunSpec(
            run_id="run-1",
            dataset_id="dataset-1",
            dataset_version="v1",
            instrument_master_version="v1",
            market_rule_version="v1",
            execution_model_version="v1",
            simulation_profile="REALISTIC",
            code_revision="abc",
            configuration_revision="cfg",
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T01:00:00Z",
        time_range_start="2026-01-01T00:00:00Z",
        time_range_end="2026-01-01T00:59:00Z",
        metrics=(("net_pnl", Decimal("10")),),
    )


def test_store_round_trips_result() -> None:
    store = InMemoryResearchStore()
    result = _result()
    store.save_result(result)
    assert store.get_result(result.result_id) == result


def test_store_rejects_duplicate_result() -> None:
    store = InMemoryResearchStore()
    result = _result()
    store.save_result(result)
    try:
        store.save_result(result)
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate result was accepted")


def test_local_filesystem_store_round_trips_result(tmp_path) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _result()

    store.save_result(result)

    assert store.get_result(result.result_id) == result


def test_local_filesystem_store_rejects_duplicate_result(tmp_path) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _result()
    store.save_result(result)

    try:
        store.save_result(result)
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate result was accepted")


def test_local_filesystem_store_round_trips_manifest(tmp_path) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    manifest = ResearchArtifactManifest(
        run_fingerprint="run-fingerprint",
        artifacts=(
            ResearchArtifact(
                artifact_id="dataset-1",
                artifact_type="dataset",
                content_hash="abc123",
                uri="data.bin",
                size_bytes=7,
                metadata={"source": "fixture"},
            ),
        ),
    )

    store.save_manifest(manifest)

    assert store.get_manifest(manifest.fingerprint()) == manifest
