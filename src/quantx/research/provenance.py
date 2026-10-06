"""Canonical provenance records and deterministic fingerprints for research runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


def canonical_scalar(value: object) -> object:
    """Return one JSON-safe canonical scalar, failing closed on unsupported types.

    Canonicalization rules: ``Decimal`` keeps its exact representation through
    ``str`` (so ``Decimal("1")`` and ``Decimal("1.0")`` stay distinct), enums use
    their canonical value, and ``None`` is preserved rather than coerced to a
    falsy default. Strings are never case-folded or whitespace-normalized. Any
    other Python object raises instead of silently stringifying.
    """

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported canonical provenance type: {type(value).__name__}")


def _canonical_pairs(pairs: tuple[tuple[str, str], ...], label: str) -> list[list[str]]:
    return [[key, value] for key, value in pairs]


@dataclass(frozen=True, slots=True)
class SimulationModelIdentity:
    """Canonical identity of one effective deterministic simulation model."""

    model_id: str
    model_version: str
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")
        keys = [key for key, _ in self.parameters]
        if any(not key.strip() for key in keys):
            raise ValueError("model parameter names must not be empty")
        if keys != sorted(keys):
            raise ValueError("model parameters must be sorted")
        if len(keys) != len(set(keys)):
            raise ValueError("model parameter names must be unique")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "parameters": _canonical_pairs(self.parameters, "model"),
        }


@dataclass(frozen=True, slots=True)
class StrategyConfiguration:
    """Canonical strategy identity for a research run.

    Absent identity is represented as ``None`` rather than invented from a
    callable or runtime state.
    """

    strategy_id: str | None = None
    strategy_version: str | None = None
    strategy_parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("strategy_id", "strategy_version"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be empty when provided")
        keys = [key for key, _ in self.strategy_parameters]
        if any(not key.strip() for key in keys):
            raise ValueError("strategy parameter names must not be empty")
        if keys != sorted(keys):
            raise ValueError("strategy parameters must be sorted")
        if len(keys) != len(set(keys)):
            raise ValueError("strategy parameter names must be unique")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_parameters": _canonical_pairs(self.strategy_parameters, "strategy"),
        }


@dataclass(frozen=True, slots=True)
class ExecutionConfiguration:
    """Effective deterministic execution/simulation configuration of one run."""

    simulation_profile_name: str
    latency_ms: int
    slippage_bps: Decimal | None = None
    partial_fill_ratio: Decimal | None = None
    fee_bps: Decimal | None = None
    execution_models: tuple[SimulationModelIdentity, ...] = ()
    volume_participation_rate: Decimal | None = None
    slippage_model: SimulationModelIdentity | None = None
    charge_model: SimulationModelIdentity | None = None

    def __post_init__(self) -> None:
        if not self.simulation_profile_name.strip():
            raise ValueError("simulation_profile_name must not be empty")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        models = list(self.execution_models)
        ordered_models = sorted(models, key=lambda item: (item.model_id, item.model_version))
        if models != ordered_models:
            raise ValueError("execution_models must be sorted")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "simulation_profile_name": self.simulation_profile_name,
            "latency_ms": self.latency_ms,
            "slippage_bps": canonical_scalar(self.slippage_bps),
            "partial_fill_ratio": canonical_scalar(self.partial_fill_ratio),
            "fee_bps": canonical_scalar(self.fee_bps),
            "execution_models": [
                model.canonical_payload()
                for model in sorted(
                    self.execution_models,
                    key=lambda item: (item.model_id, item.model_version),
                )
            ],
            "volume_participation_rate": canonical_scalar(self.volume_participation_rate),
            "slippage_model": (
                None if self.slippage_model is None else self.slippage_model.canonical_payload()
            ),
            "charge_model": (
                None if self.charge_model is None else self.charge_model.canonical_payload()
            ),
        }


@dataclass(frozen=True, slots=True)
class PolicyConfiguration:
    """Result-defining subset of execution policy context."""

    granted_capabilities: tuple[str, ...] = ()
    live_trading_enabled: bool | None = None
    manual_approval: bool | None = None

    def __post_init__(self) -> None:
        capabilities = list(self.granted_capabilities)
        if any(not item.strip() for item in capabilities):
            raise ValueError("granted capability names must not be empty")
        if capabilities != sorted(capabilities):
            raise ValueError("granted_capabilities must be sorted")
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("granted capability names must be unique")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "granted_capabilities": list(self.granted_capabilities),
            "live_trading_enabled": canonical_scalar(self.live_trading_enabled),
            "manual_approval": canonical_scalar(self.manual_approval),
        }


@dataclass(frozen=True, slots=True)
class BrokerConstraintConfiguration:
    """Material, result-affecting broker/venue constraint values."""

    name: str
    minimum_order_value: Decimal | None = None
    minimum_quantity: Decimal | None = None
    minimum_margin_amount: Decimal | None = None
    minimum_margin_currency: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("broker constraint name must not be empty")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "minimum_order_value": canonical_scalar(self.minimum_order_value),
            "minimum_quantity": canonical_scalar(self.minimum_quantity),
            "minimum_margin_amount": canonical_scalar(self.minimum_margin_amount),
            "minimum_margin_currency": self.minimum_margin_currency,
        }


@dataclass(frozen=True, slots=True)
class StartingCapitalConfiguration:
    """Configured research starting capital, without runtime identity."""

    capital_source: str
    currency: str
    cash_balance: Decimal
    available_cash: Decimal
    blocked_cash: Decimal
    margin_used: Decimal
    margin_available: Decimal
    buying_power: Decimal

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capital_source": self.capital_source,
            "currency": self.currency,
            "cash_balance": canonical_scalar(self.cash_balance),
            "available_cash": canonical_scalar(self.available_cash),
            "blocked_cash": canonical_scalar(self.blocked_cash),
            "margin_used": canonical_scalar(self.margin_used),
            "margin_available": canonical_scalar(self.margin_available),
            "buying_power": canonical_scalar(self.buying_power),
        }


@dataclass(frozen=True, slots=True)
class ResearchRunConfiguration:
    """Canonical material configuration that defines one research run.

    This is structured configuration only. It deliberately exposes no
    fingerprint or hash API: ``ResearchProvenance.fingerprint()`` remains the
    single reproducibility identity for the repository.
    """

    strategy: StrategyConfiguration = field(default_factory=StrategyConfiguration)
    execution: ExecutionConfiguration = field(
        default_factory=lambda: ExecutionConfiguration(
            simulation_profile_name="UNSPECIFIED",
            latency_ms=0,
        )
    )
    allow_incomplete: bool = False
    account_state_sampling_policy: str = "UNSPECIFIED"
    policy: PolicyConfiguration | None = None
    broker_constraints: tuple[BrokerConstraintConfiguration, ...] = ()
    starting_capital: StartingCapitalConfiguration | None = None

    def __post_init__(self) -> None:
        if not self.account_state_sampling_policy.strip():
            raise ValueError("account_state_sampling_policy must not be empty")
        names = [constraint.name for constraint in self.broker_constraints]
        if len(names) != len(set(names)):
            raise ValueError("broker constraint names must be unique")
        if self.broker_constraints != tuple(
            sorted(self.broker_constraints, key=lambda item: item.name)
        ):
            raise ValueError("broker constraints must be sorted")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "strategy": self.strategy.canonical_payload(),
            "execution": self.execution.canonical_payload(),
            "allow_incomplete": canonical_scalar(self.allow_incomplete),
            "account_state_sampling_policy": self.account_state_sampling_policy,
            "policy": None if self.policy is None else self.policy.canonical_payload(),
            "broker_constraints": [
                constraint.canonical_payload()
                for constraint in sorted(
                    self.broker_constraints,
                    key=lambda item: item.name,
                )
            ],
            "starting_capital": (
                None if self.starting_capital is None else self.starting_capital.canonical_payload()
            ),
        }


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    """Immutable inputs that define the reproducibility identity of a run."""

    dataset_id: str
    dataset_version: str
    instrument_master_version: str
    market_rule_version: str
    execution_model_version: str
    simulation_profile: str
    code_revision: str
    configuration_revision: str
    random_seed: int | None = None
    extra: Mapping[str, str] = field(default_factory=dict)
    run_configuration: ResearchRunConfiguration | None = None

    def __post_init__(self) -> None:
        required = (
            ("dataset_id", self.dataset_id),
            ("dataset_version", self.dataset_version),
            ("instrument_master_version", self.instrument_master_version),
            ("market_rule_version", self.market_rule_version),
            ("execution_model_version", self.execution_model_version),
            ("simulation_profile", self.simulation_profile),
            ("code_revision", self.code_revision),
            ("configuration_revision", self.configuration_revision),
        )
        for name, value in required:
            if not value.strip():
                raise ValueError(f"{name} must not be empty")

    def canonical_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "instrument_master_version": self.instrument_master_version,
            "market_rule_version": self.market_rule_version,
            "execution_model_version": self.execution_model_version,
            "simulation_profile": self.simulation_profile,
            "code_revision": self.code_revision,
            "configuration_revision": self.configuration_revision,
            "random_seed": self.random_seed,
            "extra": dict(sorted(self.extra.items())),
        }
        # Included only when supplied, so provenance that declares no structured
        # run configuration keeps its previous canonical payload exactly.
        if self.run_configuration is not None:
            payload["run_configuration"] = self.run_configuration.canonical_payload()
        return payload

    def fingerprint(self) -> str:
        """Return a stable SHA-256 fingerprint of canonical provenance."""
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
