from decimal import Decimal

from quantx.research.orchestrator import ResearchOrchestrator
from quantx.research.preflight import PreflightStatus, ResearchPreflightGate
from quantx.research.quality import HistoricalDataQualityGate
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import InMemoryResearchStore
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.execution.market_data import MarketSnapshot
from quantx.domain.value_objects import InstrumentId
from datetime import datetime, timezone


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
        preflight=ResearchPreflightGate(artifacts=()),
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
