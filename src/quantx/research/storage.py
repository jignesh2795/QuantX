"""Persistence boundaries for research results and provenance manifests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .artifacts import ResearchArtifact, ResearchArtifactManifest
from .provenance import (
    BrokerConstraintConfiguration,
    ExecutionConfiguration,
    PolicyConfiguration,
    ResearchProvenance,
    ResearchRunConfiguration,
    SimulationModelIdentity,
    StartingCapitalConfiguration,
    StrategyConfiguration,
)
from .result import ResearchResult, ResearchRunSpec, ResultQuality
from .run import ResearchRunRecord


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _required_str(payload: Mapping[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _optional_str(payload: Mapping[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value


def _required_int(payload: Mapping[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_int(payload: Mapping[str, object], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _optional_decimal(payload: Mapping[str, object], field_name: str) -> Decimal | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a decimal string or null")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must contain a valid decimal") from exc


def _required_bool(payload: Mapping[str, object], field_name: str) -> bool:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _optional_bool(payload: Mapping[str, object], field_name: str) -> bool | None:
    value = payload.get(field_name)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean or null")
    return value


def _pairs(payload: Mapping[str, object], field_name: str) -> tuple[tuple[str, str], ...]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
        ):
            raise ValueError(f"{field_name} must contain [string, string] pairs")
        result.append((item[0], item[1]))
    return tuple(result)


def _extra(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("extra must be an object")
    extra: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError("extra must contain string keys and values")
        extra[key] = item
    return extra


def _simulation_model(payload: Mapping[str, object]) -> SimulationModelIdentity:
    return SimulationModelIdentity(
        model_id=_required_str(payload, "model_id"),
        model_version=_required_str(payload, "model_version"),
        parameters=_pairs(payload, "parameters"),
    )


def _simulation_models(payload: Mapping[str, object]) -> tuple[SimulationModelIdentity, ...]:
    value = payload.get("execution_models")
    if not isinstance(value, list):
        raise ValueError("execution_models must be an array")
    return tuple(_simulation_model(_mapping(item, "execution model")) for item in value)


def _optional_simulation_model(
    payload: Mapping[str, object], field_name: str
) -> SimulationModelIdentity | None:
    value = payload.get(field_name)
    if value is None:
        return None
    return _simulation_model(_mapping(value, field_name))


def _policy_configuration(value: object) -> PolicyConfiguration | None:
    if value is None:
        return None
    payload = _mapping(value, "policy")
    capabilities = payload.get("granted_capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise ValueError("granted_capabilities must be an array of strings")
    return PolicyConfiguration(
        granted_capabilities=tuple(capabilities),
        live_trading_enabled=_optional_bool(payload, "live_trading_enabled"),
        manual_approval=_optional_bool(payload, "manual_approval"),
    )


def _broker_constraints(value: object) -> tuple[BrokerConstraintConfiguration, ...]:
    if not isinstance(value, list):
        raise ValueError("broker_constraints must be an array")
    return tuple(
        BrokerConstraintConfiguration(
            name=_required_str(item, "name"),
            minimum_order_value=_optional_decimal(item, "minimum_order_value"),
            minimum_quantity=_optional_decimal(item, "minimum_quantity"),
            minimum_margin_amount=_optional_decimal(item, "minimum_margin_amount"),
            minimum_margin_currency=_optional_str(item, "minimum_margin_currency"),
        )
        for item in (_mapping(raw, "broker constraint") for raw in value)
    )


def _required_decimal(payload: Mapping[str, object], field_name: str) -> Decimal:
    value = _optional_decimal(payload, field_name)
    if value is None:
        raise ValueError(f"{field_name} must be present")
    return value


def _starting_capital(value: object) -> StartingCapitalConfiguration | None:
    if value is None:
        return None
    payload = _mapping(value, "starting_capital")
    return StartingCapitalConfiguration(
        capital_source=_required_str(payload, "capital_source"),
        currency=_required_str(payload, "currency"),
        cash_balance=_required_decimal(payload, "cash_balance"),
        available_cash=_required_decimal(payload, "available_cash"),
        blocked_cash=_required_decimal(payload, "blocked_cash"),
        margin_used=_required_decimal(payload, "margin_used"),
        margin_available=_required_decimal(payload, "margin_available"),
        buying_power=_required_decimal(payload, "buying_power"),
    )


def _run_configuration(payload: Mapping[str, object]) -> ResearchRunConfiguration:
    strategy_payload = _mapping(payload.get("strategy"), "strategy")
    execution_payload = _mapping(payload.get("execution"), "execution")
    return ResearchRunConfiguration(
        strategy=StrategyConfiguration(
            strategy_id=_optional_str(strategy_payload, "strategy_id"),
            strategy_version=_optional_str(strategy_payload, "strategy_version"),
            strategy_parameters=_pairs(strategy_payload, "strategy_parameters"),
        ),
        execution=ExecutionConfiguration(
            simulation_profile_name=_required_str(execution_payload, "simulation_profile_name"),
            latency_ms=_required_int(execution_payload, "latency_ms"),
            slippage_bps=_optional_decimal(execution_payload, "slippage_bps"),
            partial_fill_ratio=_optional_decimal(execution_payload, "partial_fill_ratio"),
            fee_bps=_optional_decimal(execution_payload, "fee_bps"),
            execution_models=_simulation_models(execution_payload),
            volume_participation_rate=_optional_decimal(
                execution_payload, "volume_participation_rate"
            ),
            slippage_model=_optional_simulation_model(execution_payload, "slippage_model"),
            charge_model=_optional_simulation_model(execution_payload, "charge_model"),
        ),
        allow_incomplete=_required_bool(payload, "allow_incomplete"),
        account_state_sampling_policy=_required_str(payload, "account_state_sampling_policy"),
        policy=_policy_configuration(payload.get("policy")),
        broker_constraints=_broker_constraints(payload.get("broker_constraints")),
        starting_capital=_starting_capital(payload.get("starting_capital")),
    )


class ResearchRunRepository(Protocol):
    """Database-neutral persistence contract for research execution instances."""

    def create_run(self, run: ResearchRunRecord) -> ResearchRunRecord: ...
    def get_run(self, run_id: str) -> ResearchRunRecord | None: ...
    def find_by_provenance_fingerprint(
        self, provenance_fingerprint: str
    ) -> tuple[ResearchRunRecord, ...]: ...
    def start_run(self, run_id: str, started_at: str) -> ResearchRunRecord: ...
    def complete_run(
        self, run_id: str, result: ResearchResult, completed_at: str
    ) -> ResearchRunRecord: ...
    def attach_manifest(
        self,
        run_id: str,
        manifest: ResearchArtifactManifest,
    ) -> ResearchRunRecord: ...
    def fail_run(self, run_id: str, reason: str) -> ResearchRunRecord: ...


@dataclass(slots=True)
class InMemoryResearchRunRepository:
    """Deterministic test/dev implementation of the research run boundary."""

    _runs: dict[str, ResearchRunRecord]

    def __init__(self) -> None:
        self._runs = {}

    def create_run(self, run: ResearchRunRecord) -> ResearchRunRecord:
        if run.run_id in self._runs:
            raise ValueError("research run already exists")
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        return self._runs.get(run_id)

    def find_by_provenance_fingerprint(
        self, provenance_fingerprint: str
    ) -> tuple[ResearchRunRecord, ...]:
        if not provenance_fingerprint.strip():
            raise ValueError("provenance fingerprint must not be empty")
        matches = [
            run
            for run in self._runs.values()
            if run.provenance_fingerprint == provenance_fingerprint
        ]
        return tuple(sorted(matches, key=lambda item: (item.created_at, item.run_id)))

    def start_run(self, run_id: str, started_at: str) -> ResearchRunRecord:
        current = self._require_run(run_id)
        updated = current.started(started_at)
        self._runs[run_id] = updated
        return updated

    def complete_run(
        self, run_id: str, result: ResearchResult, completed_at: str
    ) -> ResearchRunRecord:
        current = self._require_run(run_id)
        updated = current.completed(result, completed_at)
        self._runs[run_id] = updated
        return updated

    def attach_manifest(self, run_id: str, manifest: ResearchArtifactManifest) -> ResearchRunRecord:
        current = self._require_run(run_id)
        updated = current.with_manifest(manifest)
        self._runs[run_id] = updated
        return updated

    def fail_run(self, run_id: str, reason: str) -> ResearchRunRecord:
        current = self._require_run(run_id)
        updated = current.failed(reason)
        self._runs[run_id] = updated
        return updated

    def _require_run(self, run_id: str) -> ResearchRunRecord:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"research run not found: {run_id}") from exc


class ResearchStore(Protocol):
    def save_result(self, result: ResearchResult) -> None: ...
    def get_result(self, result_id: UUID) -> ResearchResult | None: ...
    def save_manifest(self, manifest: ResearchArtifactManifest) -> None: ...
    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None: ...


@dataclass(slots=True)
class InMemoryResearchStore:
    """Deterministic test/dev implementation of the persistence boundary."""

    _results: dict[UUID, ResearchResult]
    _manifests: dict[str, ResearchArtifactManifest]

    def __init__(self) -> None:
        self._results = {}
        self._manifests = {}

    def save_result(self, result: ResearchResult) -> None:
        if result.result_id in self._results:
            raise ValueError("research result already exists")
        self._results[result.result_id] = result

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        return self._results.get(result_id)

    def save_manifest(self, manifest: ResearchArtifactManifest) -> None:
        manifest_id = manifest.fingerprint()
        if manifest_id in self._manifests:
            raise ValueError("research artifact manifest already exists")
        self._manifests[manifest_id] = manifest

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        return self._manifests.get(manifest_id)


class LocalFilesystemResearchStore:
    """Content-addressed local persistence for research metadata.

    Only metadata is persisted here; artifact payloads remain at the URIs in
    their manifests. Writes are atomic via temporary files and ``replace``.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._results_dir = self._root / "results"
        self._manifests_dir = self._root / "manifests"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: ResearchResult) -> None:
        path = self._results_dir / f"{result.result_id}.json"
        if path.exists():
            raise ValueError("research result already exists")
        self._atomic_write(path, self._result_payload(result))

    def get_result(self, result_id: UUID) -> ResearchResult | None:
        path = self._results_dir / f"{result_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return self._result_from_payload(payload)

    def save_manifest(self, manifest: ResearchArtifactManifest) -> None:
        manifest_id = manifest.fingerprint()
        path = self._manifests_dir / f"{manifest_id}.json"
        if path.exists():
            raise ValueError("research artifact manifest already exists")
        self._atomic_write(path, manifest.canonical_payload())

    def get_manifest(self, manifest_id: str) -> ResearchArtifactManifest | None:
        path = self._manifests_dir / f"{manifest_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return research_manifest_from_payload(payload)

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, object]) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    @staticmethod
    def _result_payload(result: ResearchResult) -> dict[str, object]:
        provenance = result.provenance
        assert provenance is not None
        return {
            "result_id": str(result.result_id),
            "spec": {
                "run_id": result.spec.run_id,
                "dataset_id": result.spec.dataset_id,
                "dataset_version": result.spec.dataset_version,
                "instrument_master_version": result.spec.instrument_master_version,
                "market_rule_version": result.spec.market_rule_version,
                "execution_model_version": result.spec.execution_model_version,
                "simulation_profile": result.spec.simulation_profile,
                "code_revision": result.spec.code_revision,
                "configuration_revision": result.spec.configuration_revision,
                "random_seed": result.spec.random_seed,
                **(
                    {"run_configuration": result.spec.run_configuration.canonical_payload()}
                    if result.spec.run_configuration is not None
                    else {}
                ),
            },
            "quality": result.quality.value,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "time_range_start": result.time_range_start,
            "time_range_end": result.time_range_end,
            "metrics": [[key, str(value)] for key, value in result.metrics],
            "assumptions": list(result.assumptions),
            "limitations": list(result.limitations),
            "provenance": provenance.canonical_payload(),
        }

    @staticmethod
    def _result_from_payload(payload: dict[str, object]) -> ResearchResult:
        spec_payload = _mapping(payload.get("spec"), "spec")
        spec_configuration = (
            _run_configuration(_mapping(spec_payload["run_configuration"], "run_configuration"))
            if "run_configuration" in spec_payload
            else None
        )
        spec = ResearchRunSpec(
            run_id=_required_str(spec_payload, "run_id"),
            dataset_id=_required_str(spec_payload, "dataset_id"),
            dataset_version=_required_str(spec_payload, "dataset_version"),
            instrument_master_version=_required_str(spec_payload, "instrument_master_version"),
            market_rule_version=_required_str(spec_payload, "market_rule_version"),
            execution_model_version=_required_str(spec_payload, "execution_model_version"),
            simulation_profile=_required_str(spec_payload, "simulation_profile"),
            code_revision=_required_str(spec_payload, "code_revision"),
            configuration_revision=_required_str(spec_payload, "configuration_revision"),
            random_seed=_optional_int(spec_payload, "random_seed"),
            run_configuration=spec_configuration,
        )
        provenance_payload = _mapping(payload.get("provenance"), "provenance")
        provenance = research_provenance_from_payload(provenance_payload)
        return ResearchResult(
            spec=spec,
            quality=ResultQuality(payload["quality"]),
            started_at=payload["started_at"],
            completed_at=payload["completed_at"],
            time_range_start=payload["time_range_start"],
            time_range_end=payload["time_range_end"],
            metrics=tuple((key, Decimal(value)) for key, value in payload["metrics"]),
            assumptions=tuple(payload["assumptions"]),
            limitations=tuple(payload["limitations"]),
            result_id=UUID(payload["result_id"]),
            provenance=provenance,
        )


def research_result_to_payload(result: ResearchResult) -> dict[str, object]:
    """Return the canonical payload used by research result persistence."""
    return LocalFilesystemResearchStore._result_payload(result)


def research_result_from_payload(payload: dict[str, object]) -> ResearchResult:
    """Reconstruct a result through the canonical typed persistence decoder."""
    return LocalFilesystemResearchStore._result_from_payload(payload)


def research_provenance_from_payload(
    payload: Mapping[str, object],
) -> ResearchProvenance:
    """Reconstruct provenance through the canonical typed persistence decoder."""
    configuration = (
        _run_configuration(_mapping(payload["run_configuration"], "run_configuration"))
        if "run_configuration" in payload
        else None
    )
    return ResearchProvenance(
        dataset_id=_required_str(payload, "dataset_id"),
        dataset_version=_required_str(payload, "dataset_version"),
        instrument_master_version=_required_str(payload, "instrument_master_version"),
        market_rule_version=_required_str(payload, "market_rule_version"),
        execution_model_version=_required_str(payload, "execution_model_version"),
        simulation_profile=_required_str(payload, "simulation_profile"),
        code_revision=_required_str(payload, "code_revision"),
        configuration_revision=_required_str(payload, "configuration_revision"),
        random_seed=_optional_int(payload, "random_seed"),
        extra=_extra(payload.get("extra")),
        run_configuration=configuration,
    )


def research_manifest_from_payload(
    payload: Mapping[str, object],
) -> ResearchArtifactManifest:
    """Reconstruct an artifact manifest through typed validation."""
    manifest_payload = _mapping(payload, "manifest")
    artifacts_payload = manifest_payload.get("artifacts")
    if not isinstance(artifacts_payload, list):
        raise ValueError("artifacts must be an array")
    artifacts: list[ResearchArtifact] = []
    for raw_artifact in artifacts_payload:
        artifact_payload = _mapping(raw_artifact, "artifact")
        metadata_value = artifact_payload.get("metadata")
        metadata: dict[str, str] = {}
        if metadata_value is not None:
            metadata_payload = _mapping(metadata_value, "metadata")
            for key, value in metadata_payload.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise ValueError("metadata must contain string keys and values")
                metadata[key] = value
        artifacts.append(
            ResearchArtifact(
                artifact_id=_required_str(artifact_payload, "artifact_id"),
                artifact_type=_required_str(artifact_payload, "artifact_type"),
                content_hash=_required_str(artifact_payload, "content_hash"),
                uri=_required_str(artifact_payload, "uri"),
                size_bytes=_optional_int(artifact_payload, "size_bytes"),
                metadata=metadata,
            )
        )
    return ResearchArtifactManifest(
        run_fingerprint=_required_str(manifest_payload, "run_fingerprint"),
        manifest_version=_required_str(manifest_payload, "manifest_version"),
        artifacts=tuple(artifacts),
    )
