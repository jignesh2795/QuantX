from decimal import Decimal
from uuid import uuid4

from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import InMemoryResearchStore


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
