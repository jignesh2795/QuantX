from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.orchestrator import ResearchOrchestrator
from quantx.research.preflight import ResearchPreflightGate
from quantx.research.quality import DataQualityStatus, HistoricalDataQualityGate
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import InMemoryResearchStore


def _series():
    return HistoricalDataSeries(
        (
            HistoricalObservation(
                instrument="NSE:TCS",
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                sequence=1,
                snapshot={"last": Decimal("100")},
                source_id="test",
                dataset_version="v1",
            ),
        )
    )


def _result(frames: int, quality: DataQualityStatus) -> ResearchResult:
    return ResearchResult(
        spec=ResearchRunSpec(
            run_id=f"run-{frames}",
            dataset_id="dataset",
            dataset_version="v1",
            instrument_master_version="i1",
            market_rule_version="m1",
            execution_model_version="e1",
            simulation_profile="BASIC",
            code_revision="c1",
            configuration_revision="cfg1",
        ),
        quality=ResultQuality.COMPLETE_OBSERVED if quality is DataQualityStatus.COMPLETE else ResultQuality.INCOMPLETE,
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        time_range_start="2026-01-01T00:00:00+00:00",
        time_range_end="2026-01-01T00:00:00+00:00",
        metrics=(("frames", Decimal(frames)),),
    )


def test_orchestrator_blocks_when_required_artifact_cannot_be_verified(tmp_path: Path) -> None:
    missing = tmp_path / "missing.parquet"
    manifest = ResearchArtifactManifest(
        run_fingerprint="run-fingerprint",
        artifacts=(
            ResearchArtifact(
                artifact_id="dataset",
                artifact_type="dataset",
                content_hash="00" * 32,
                uri=f"file://{missing}",
            ),
        ),
    )
    orchestrator = ResearchOrchestrator(
        preflight=ResearchPreflightGate(),
        quality_gate=HistoricalDataQualityGate(),
        store=InMemoryResearchStore(),
    )
    outcome = orchestrator.run(
        manifest=manifest,
        series=_series(),
        result_factory=_result,
    )
    assert outcome.preflight_status.value == "BLOCKED"
    assert outcome.replayed_frames == 0
    assert outcome.result is None


def test_orchestrator_runs_complete_dataset_after_preflight(tmp_path: Path) -> None:
    payload = b"historical-data"
    artifact = tmp_path / "dataset.bin"
    artifact.write_bytes(payload)
    import hashlib

    manifest = ResearchArtifactManifest(
        run_fingerprint="run-fingerprint",
        artifacts=(
            ResearchArtifact(
                artifact_id="dataset",
                artifact_type="dataset",
                content_hash=hashlib.sha256(payload).hexdigest(),
                uri=f"file://{artifact}",
            ),
        ),
    )
    store = InMemoryResearchStore()
    orchestrator = ResearchOrchestrator(
        preflight=ResearchPreflightGate(),
        quality_gate=HistoricalDataQualityGate(),
        store=store,
    )
    outcome = orchestrator.run(
        manifest=manifest,
        series=_series(),
        result_factory=_result,
    )
    assert outcome.preflight_status.value == "READY"
    assert outcome.data_quality_status is DataQualityStatus.COMPLETE
    assert outcome.replayed_frames == 1
    assert outcome.result is not None
    assert store.get_result(outcome.result.result_id) == outcome.result
