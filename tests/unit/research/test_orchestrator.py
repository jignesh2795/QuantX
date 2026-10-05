from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.orchestrator import ResearchOrchestrator
from quantx.research.preflight import ResearchPreflightGate
from quantx.research.quality import DataQualityStatus, HistoricalDataQualityGate
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import InMemoryResearchStore


def test_research_orchestrator_runs_without_quality_argument_mismatch() -> None:
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    series = HistoricalDataSeries((
        HistoricalObservation(snapshot, "test", "1", 0),
    ))
    store = InMemoryResearchStore()
    orchestrator = ResearchOrchestrator(
        preflight=ResearchPreflightGate(),
        quality_gate=HistoricalDataQualityGate(),
        store=store,
    )
    spec = ResearchRunSpec(
        run_id="run-1",
        dataset_id="test",
        dataset_version="1",
        instrument_master_version="1",
        market_rule_version="1",
        execution_model_version="1",
        simulation_profile="paper",
        code_revision="test",
        configuration_revision="test",
    )
    result = orchestrator.run(
        series=series,
        result_factory=lambda count: ResearchResult(
            spec=spec,
            quality=ResultQuality.COMPLETE_OBSERVED,
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:05:00+00:00",
            time_range_start="2026-01-01T00:00:00+00:00",
            time_range_end="2026-01-01T00:05:00+00:00",
            metrics=(("frames", Decimal(count)),),
        ),
    )
    assert result.replayed_frames == 1
    assert result.result is not None
    assert result.runnable


def test_degraded_duplicate_data_requires_explicit_opt_in() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshot = MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    series = HistoricalDataSeries(
        (
            HistoricalObservation(snapshot, "test", "1", 0),
            HistoricalObservation(snapshot, "test", "1", 1),
        )
    )
    store = InMemoryResearchStore()
    orchestrator = ResearchOrchestrator(
        preflight=ResearchPreflightGate(),
        quality_gate=HistoricalDataQualityGate(),
        store=store,
    )
    spec = ResearchRunSpec(
        run_id="run-degraded",
        dataset_id="test",
        dataset_version="1",
        instrument_master_version="1",
        market_rule_version="1",
        execution_model_version="1",
        simulation_profile="paper",
        code_revision="test",
        configuration_revision="test",
    )

    blocked = orchestrator.run(
        series=series,
        result_factory=lambda count: ResearchResult(
            spec=spec,
            quality=ResultQuality.COMPLETE_OBSERVED,
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:05:00+00:00",
            time_range_start="2026-01-01T00:00:00+00:00",
            time_range_end="2026-01-01T00:05:00+00:00",
            metrics=(("frames", Decimal(count)),),
        ),
    )

    assert blocked.result is None
    assert blocked.data_quality_status is DataQualityStatus.INCOMPLETE
    assert blocked.runnable is False

    allowed = orchestrator.run(
        series=series,
        allow_incomplete=True,
        result_factory=lambda count: ResearchResult(
            spec=spec,
            quality=ResultQuality.INCOMPLETE,
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:05:00+00:00",
            time_range_start="2026-01-01T00:00:00+00:00",
            time_range_end="2026-01-01T00:05:00+00:00",
            metrics=(("frames", Decimal(count)),),
        ),
    )

    assert allowed.result is not None
    assert allowed.data_quality_status is DataQualityStatus.INCOMPLETE
    assert allowed.runnable is False
    assert allowed.replayed_frames == 2
