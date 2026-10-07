import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from quantx.research.artifacts import ResearchArtifact, ResearchArtifactManifest
from quantx.research.provenance import (
    BrokerConstraintConfiguration,
    ExecutionConfiguration,
    PolicyConfiguration,
    ResearchProvenance,
    ResearchRunConfiguration,
    SimulationModelIdentity,
    StartingCapitalConfiguration,
    StrategyConfiguration,
)
from quantx.research.result import ResearchResult, ResearchRunSpec, ResultQuality
from quantx.research.storage import LocalFilesystemResearchStore, research_result_from_payload


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


def _structured_configuration() -> ResearchRunConfiguration:
    return ResearchRunConfiguration(
        strategy=StrategyConfiguration(
            strategy_id="mean-reversion",
            strategy_version="2",
            strategy_parameters=(("lookback", "20"), ("threshold", "1.5")),
        ),
        execution=ExecutionConfiguration(
            simulation_profile_name="REALISTIC",
            latency_ms=25,
            slippage_bps=Decimal("1.0"),
            partial_fill_ratio=Decimal("0.75"),
            fee_bps=Decimal("2"),
            execution_models=(
                SimulationModelIdentity(
                    model_id="candle-fill",
                    model_version="v4",
                    parameters=(("rule", "close-cross"),),
                ),
                SimulationModelIdentity(
                    model_id="quote-fill",
                    model_version="v3",
                ),
            ),
            volume_participation_rate=Decimal("0.20"),
            slippage_model=SimulationModelIdentity(
                model_id="slippage-bps",
                model_version="v1",
                parameters=(("basis_points", "1.0"),),
            ),
            charge_model=SimulationModelIdentity(
                model_id="percentage-bps",
                model_version="v1",
                parameters=(("component_name", "fee"), ("rate_bps", "2")),
            ),
        ),
        allow_incomplete=True,
        account_state_sampling_policy="AS_OF_OBSERVED",
        policy=PolicyConfiguration(
            granted_capabilities=("market.read", "strategy.evaluate"),
            live_trading_enabled=False,
            manual_approval=True,
        ),
        broker_constraints=(
            BrokerConstraintConfiguration(
                name="NSE",
                minimum_order_value=Decimal("100.0"),
                minimum_quantity=Decimal("1"),
                minimum_margin_amount=Decimal("500.00"),
                minimum_margin_currency="INR",
            ),
        ),
        starting_capital=StartingCapitalConfiguration(
            capital_source="paper-account",
            currency="INR",
            cash_balance=Decimal("10000.0"),
            available_cash=Decimal("9000.00"),
            blocked_cash=Decimal("500"),
            margin_used=Decimal("500.0"),
            margin_available=Decimal("5000.00"),
            buying_power=Decimal("14000"),
        ),
    )


def _structured_result() -> ResearchResult:
    configuration = _structured_configuration()
    provenance = ResearchProvenance(
        dataset_id="nse-1m",
        dataset_version="2026-08-20",
        instrument_master_version="v1",
        market_rule_version="v1",
        execution_model_version="paper-core-v0.1",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg1",
        random_seed=7,
        run_configuration=configuration,
    )
    return ResearchResult(
        spec=ResearchRunSpec(
            run_id="run-structured-1",
            dataset_id="nse-1m",
            dataset_version="2026-08-20",
            instrument_master_version="v1",
            market_rule_version="v1",
            execution_model_version="paper-core-v0.1",
            simulation_profile="REALISTIC",
            code_revision="abc123",
            configuration_revision="cfg1",
            random_seed=7,
            run_configuration=configuration,
        ),
        quality=ResultQuality.COMPLETE_OBSERVED,
        started_at="2026-08-20T10:00:00Z",
        completed_at="2026-08-20T10:01:00Z",
        time_range_start="2026-08-20T09:00:00Z",
        time_range_end="2026-08-20T10:00:00Z",
        metrics=(("return", Decimal("0.12")),),
        assumptions=("deterministic simulation",),
        limitations=("simulated execution",),
        result_id=UUID("00000000-0000-0000-0000-000000000002"),
        provenance=provenance,
    )


def test_filesystem_structured_result_round_trip_preserves_c12_configuration(
    tmp_path: Path,
) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _structured_result()

    store.save_result(result)

    restored = store.get_result(result.result_id)

    assert restored is not None
    assert restored == result
    assert restored.spec.run_configuration == result.spec.run_configuration
    assert restored.provenance.run_configuration == result.provenance.run_configuration
    assert restored.fingerprint == result.fingerprint
    assert restored.reproducibility_key == result.reproducibility_key


def test_filesystem_structured_result_rejects_malformed_configuration(
    tmp_path: Path,
) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _structured_result()
    store.save_result(result)
    path = tmp_path / "results" / (str(result.result_id) + ".json")

    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["spec"]["run_configuration"]["execution"]["latency_ms"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="latency_ms"):
        store.get_result(result.result_id)


def test_structured_configuration_rejects_unsorted_execution_models() -> None:
    with pytest.raises(ValueError, match="execution_models must be sorted"):
        ExecutionConfiguration(
            simulation_profile_name="REALISTIC",
            latency_ms=0,
            execution_models=(
                SimulationModelIdentity(model_id="QUOTE", model_version="v1"),
                SimulationModelIdentity(model_id="BASIC_BAR", model_version="v1"),
            ),
        )


def test_structured_configuration_rejects_unsorted_broker_constraints() -> None:
    with pytest.raises(ValueError, match="broker constraints must be sorted"):
        ResearchRunConfiguration(
            broker_constraints=(
                BrokerConstraintConfiguration(name="Z"),
                BrokerConstraintConfiguration(name="A"),
            ),
        )


def test_filesystem_structured_result_rejects_invalid_provenance_configuration(
    tmp_path: Path,
) -> None:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _structured_result()
    store.save_result(result)
    path = tmp_path / "results" / (str(result.result_id) + ".json")

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["provenance"]["run_configuration"]["execution"]["latency_ms"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="latency_ms"):
        store.get_result(result.result_id)


def _saved_result(tmp_path: Path) -> tuple[LocalFilesystemResearchStore, Path, UUID]:
    store = LocalFilesystemResearchStore(tmp_path)
    result = _result()
    store.save_result(result)
    path = tmp_path / "results" / (str(result.result_id) + ".json")
    return store, path, result.result_id


def test_filesystem_result_decoder_rejects_non_object_root(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="result must be an object"):
        store.get_result(result_id)


def test_filesystem_result_decoder_public_path_round_trips_valid_payload(
    tmp_path: Path,
) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    restored = research_result_from_payload(payload)

    assert restored.result_id == result_id
    assert restored.metric("return") == Decimal("0.12")
    assert restored.fingerprint == store.get_result(result_id).fingerprint


def test_filesystem_result_decoder_rejects_malformed_metric_shape(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"] = [["return"]]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics must contain \[string, decimal-string\] pairs"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_non_string_metric_name(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"] = [[7, "0.12"]]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics must contain"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_non_string_metric_value(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"] = [["return", 0.12]]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics must contain"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_invalid_metric_decimal(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"] = [["return", "not-a-decimal"]]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics must contain valid decimal strings"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_assumptions_string(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assumptions"] = "not-an-array"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="assumptions must be an array"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_non_string_assumption(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assumptions"] = [7]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="assumptions must contain strings"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_limitations_string(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["limitations"] = "not-an-array"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="limitations must be an array"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_non_string_limitation(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["limitations"] = [7]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="limitations must contain strings"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_invalid_quality(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["quality"] = "UNKNOWN_QUALITY"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="quality must be a valid ResultQuality value"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_non_string_timestamp(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["started_at"] = 123
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="started_at must be a string"):
        store.get_result(result_id)


def test_filesystem_result_decoder_rejects_invalid_result_id(tmp_path: Path) -> None:
    store, path, result_id = _saved_result(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["result_id"] = "not-a-uuid"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="result_id must contain a valid UUID"):
        store.get_result(result_id)
