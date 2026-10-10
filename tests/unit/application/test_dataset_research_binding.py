"""Tests for binding ingestion results to the research-run identity."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.dataset_ingestion import HistoricalDatasetIngestionResult
from quantx.application.dataset_research_binding import research_run_spec_from_ingestion
from quantx.application.research_run import ResearchRunApplicationService
from quantx.domain.clock import FixedClock
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.research.data_quality import (
    CompletenessStatus,
    DataQualityStatus,
    HistoricalDataQuality,
    assess_candles,
)
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.provenance import ResearchProvenance, ResearchRunConfiguration
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunState
from quantx.research.storage import InMemoryResearchRunRepository


def _version(
    dataset_id="nse-equities",
    version="2026-01",
    source_id="dhan",
) -> DatasetVersion:
    return DatasetVersion(
        identity=DatasetIdentity(
            dataset_id=dataset_id,
            version=version,
            source_id=source_id,
            schema_version="1",
            content_fingerprint=fingerprint_bytes(b"declared"),
        )
    )


def _quality() -> HistoricalDataQuality:
    return HistoricalDataQuality(
        quality=DataQualityStatus.VALID,
        completeness=CompletenessStatus.COMPLETE,
        observation_count=2,
        expected_count=2,
        missing_timestamps=(),
        unexpected_timestamps=(),
        duplicate_timestamps=(),
        out_of_order=False,
        issues=(),
    )


def _result() -> HistoricalDatasetIngestionResult:
    return HistoricalDatasetIngestionResult(
        dataset_version=_version(),
        dataset_id="nse-equities",
        version="2026-01",
        source_id="dhan",
        inserted_count=2,
        quality=_quality(),
    )


def _bind(result=None, **overrides):
    values = {
        "run_id": "run-1",
        "instrument_master_version": "instruments-v1",
        "market_rule_version": "rules-v1",
        "execution_model_version": "model-v1",
        "simulation_profile": "paper-v1",
        "code_revision": "code-v1",
        "configuration_revision": "config-v1",
    }
    values.update(overrides)
    return research_run_spec_from_ingestion(
        _result() if result is None else result, **values
    )


def test_binding_uses_registered_dataset_identity() -> None:
    spec = _bind()
    assert isinstance(spec, ResearchRunSpec)
    assert spec.dataset_id == "nse-equities"
    assert spec.dataset_version == "2026-01"
    assert spec.instrument_master_version == "instruments-v1"
    assert spec.market_rule_version == "rules-v1"
    assert spec.execution_model_version == "model-v1"
    assert spec.simulation_profile == "paper-v1"
    assert spec.code_revision == "code-v1"
    assert spec.configuration_revision == "config-v1"
    assert spec.random_seed is None
    assert spec.run_configuration is None


def test_binding_preserves_seed_and_structured_configuration() -> None:
    configuration = ResearchRunConfiguration()
    spec = _bind(random_seed=7, run_configuration=configuration)
    assert spec.random_seed == 7
    assert spec.run_configuration == configuration


def test_binding_provenance_matches_canonical_fingerprint() -> None:
    configuration = ResearchRunConfiguration()
    spec = _bind(random_seed=7, run_configuration=configuration)
    expected = ResearchProvenance(
        dataset_id="nse-equities",
        dataset_version="2026-01",
        instrument_master_version="instruments-v1",
        market_rule_version="rules-v1",
        execution_model_version="model-v1",
        simulation_profile="paper-v1",
        code_revision="code-v1",
        configuration_revision="config-v1",
        random_seed=7,
        run_configuration=configuration,
    )
    assert spec.to_provenance() == expected
    assert spec.to_provenance().fingerprint() == expected.fingerprint()


@pytest.mark.parametrize("field", ["dataset_id", "version", "source_id"])
def test_mismatched_identity_fields_fail_closed(field) -> None:
    result = replace(_result(), **{field: "mismatched"})
    with pytest.raises(ValueError, match="registered dataset identity"):
        _bind(result)


def test_missing_required_inputs_are_not_inferred() -> None:
    with pytest.raises(ValueError, match="code_revision"):
        _bind(code_revision="")
    with pytest.raises(TypeError):
        research_run_spec_from_ingestion(_result(), run_id="run-1")


def test_bound_spec_completes_durable_run_lifecycle() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = ResearchRunApplicationService(repository=repository, clock=clock)
    spec = _bind()
    result = ResearchResult(
        spec=spec,
        quality=ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS,
        started_at="2026-10-06T10:00:00+00:00",
        completed_at="2026-10-06T10:05:00+00:00",
        time_range_start="2026-01-01T09:15:00+00:00",
        time_range_end="2026-01-01T15:30:00+00:00",
        metrics=(("executed_count", Decimal("2")),),
    )
    execution = service.execute(spec, lambda: result)
    assert execution.run.state is ResearchRunState.COMPLETED
    assert execution.run.provenance_fingerprint == spec.to_provenance().fingerprint()
    stored = repository.get_run(spec.run_id)
    assert stored is not None
    assert stored == execution.run


def _assessed_candle(timestamp) -> Candle:
    return Candle(
        instrument=InstrumentId("NSE", "TCS"),
        timeframe="1m",
        timestamp=timestamp,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("1000"),
    )


_T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expected_timestamps", "completeness"),
    [
        (None, CompletenessStatus.UNKNOWN),
        ((_T0, _T1, _T2), CompletenessStatus.INCOMPLETE),
    ],
)
def test_composition_preserves_unknown_or_incomplete_quality(
    expected_timestamps, completeness
) -> None:
    candles = (_assessed_candle(_T0), _assessed_candle(_T1))
    quality = assess_candles(candles, expected_timestamps)
    assert quality.completeness is completeness
    result = HistoricalDatasetIngestionResult(
        dataset_version=_version(),
        dataset_id="nse-equities",
        version="2026-01",
        source_id="dhan",
        inserted_count=2,
        quality=quality,
    )
    spec = _bind(result)
    assert spec.dataset_id == "nse-equities"
    assert spec.dataset_version == "2026-01"
    assert spec.to_provenance().dataset_id == "nse-equities"
    assert spec.to_provenance().dataset_version == "2026-01"
    assert result.quality is quality
    assert result.quality.completeness is completeness
