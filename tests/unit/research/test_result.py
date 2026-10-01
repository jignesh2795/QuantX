from decimal import Decimal

from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality


def _spec() -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id="run-1",
        dataset_id="nse-1m",
        dataset_version="2026-08-20",
        instrument_master_version="nse-contracts-v1",
        market_rule_version="india-rules-v1",
        execution_model_version="paper-core-v0.1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg123",
        random_seed=42,
    )


def test_research_result_preserves_provenance_and_metric_lookup() -> None:
    result = ResearchResult(
        spec=_spec(),
        quality=ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS,
        started_at="2026-08-20T09:00:00Z",
        completed_at="2026-08-20T09:01:00Z",
        time_range_start="2026-08-19T09:15:00Z",
        time_range_end="2026-08-19T15:30:00Z",
        metrics=(("net_pnl", Decimal("125.50")),),
        assumptions=("fees from market-rule version",),
    )
    assert result.metric("net_pnl") == Decimal("125.50")
    assert result.metric("missing") is None
    assert result.spec.dataset_version == "2026-08-20"
    assert result.reproducibility_key[-1] == "42"


def test_incomplete_result_is_explicit() -> None:
    result = ResearchResult(
        spec=_spec(),
        quality=ResultQuality.INCOMPLETE,
        started_at="2026-08-20T09:00:00Z",
        completed_at="2026-08-20T09:01:00Z",
        time_range_start="2026-08-19T09:15:00Z",
        time_range_end="2026-08-19T15:30:00Z",
        limitations=("missing quote data",),
    )
    assert result.quality is ResultQuality.INCOMPLETE
    assert result.limitations == ("missing quote data",)
