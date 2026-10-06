"""R1-C12 adversarial coverage for canonical research run configuration."""

from dataclasses import replace
from decimal import Decimal

import pytest

from quantx.execution.charges import PercentageBpsChargeModel
from quantx.execution.models import SlippageModel
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
from quantx.research.result import ResearchRunSpec

BASELINE = ResearchProvenance(
    dataset_id="nse-eq",
    dataset_version="v1",
    instrument_master_version="instr-v3",
    market_rule_version="rules-v2",
    execution_model_version="paper-core-v0.3",
    simulation_profile="REALISTIC",
    code_revision="abc123",
    configuration_revision="cfg9",
)

# SlippageModel is a slots dataclass: its class-level defaults are member
# descriptors, so identity must be read from an instance.
_SLIPPAGE = SlippageModel()


def _strategy(
    strategy_id: str = "sma",
    version: str = "1",
    parameters: tuple[tuple[str, str], ...] = (("window", "20"),),
) -> StrategyConfiguration:
    return StrategyConfiguration(
        strategy_id=strategy_id,
        strategy_version=version,
        strategy_parameters=parameters,
    )


def _execution(
    *,
    profile_name: str = "REALISTIC",
    latency_ms: int = 0,
    slippage_bps: Decimal | None = Decimal("0"),
    partial_fill_ratio: Decimal | None = Decimal("1"),
    fee_bps: Decimal | None = Decimal("0"),
    execution_models: tuple[SimulationModelIdentity, ...] = (
        SimulationModelIdentity(model_id="QUOTE", model_version="paper-core-v0.3"),
    ),
    volume_participation_rate: Decimal | None = None,
    slippage_model: SimulationModelIdentity | None = None,
    charge_model: SimulationModelIdentity | None = None,
) -> ExecutionConfiguration:
    return ExecutionConfiguration(
        simulation_profile_name=profile_name,
        latency_ms=latency_ms,
        slippage_bps=slippage_bps,
        partial_fill_ratio=partial_fill_ratio,
        fee_bps=fee_bps,
        execution_models=execution_models,
        volume_participation_rate=volume_participation_rate,
        slippage_model=slippage_model,
        charge_model=charge_model,
    )


def _configuration(**overrides) -> ResearchRunConfiguration:
    values = {
        "strategy": _strategy(),
        "execution": _execution(),
        "allow_incomplete": False,
        "account_state_sampling_policy": "EXACT_CURRENT",
        "policy": PolicyConfiguration(),
        "broker_constraints": (),
        "starting_capital": StartingCapitalConfiguration(
            capital_source="backtest_configured",
            currency="INR",
            cash_balance=Decimal("1000"),
            available_cash=Decimal("1000"),
            blocked_cash=Decimal("0"),
            margin_used=Decimal("0"),
            margin_available=Decimal("1000"),
            buying_power=Decimal("1000"),
        ),
    }
    values.update(overrides)
    return ResearchRunConfiguration(**values)


def _with(configuration: ResearchRunConfiguration) -> ResearchProvenance:
    return replace(BASELINE, run_configuration=configuration)


# --------------------------------------------------------------------------
# Fingerprint equality
# --------------------------------------------------------------------------


def test_identical_configuration_yields_identical_fingerprint() -> None:
    assert _with(_configuration()).fingerprint() == _with(_configuration()).fingerprint()


def test_reordering_mapping_keys_does_not_change_fingerprint() -> None:
    forward = ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="v1",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="paper-core-v0.3",
        simulation_profile="REALISTIC",
        code_revision="abc123",
        configuration_revision="cfg9",
        extra={"a": "1", "b": "2"},
    )
    reordered = ResearchProvenance(
        code_revision="abc123",
        configuration_revision="cfg9",
        simulation_profile="REALISTIC",
        execution_model_version="paper-core-v0.3",
        market_rule_version="rules-v2",
        instrument_master_version="instr-v3",
        dataset_version="v1",
        dataset_id="nse-eq",
        extra={"b": "2", "a": "1"},
    )
    assert forward.fingerprint() == reordered.fingerprint()


def test_equivalent_unordered_collections_yield_identical_fingerprint() -> None:
    ordered = _configuration(
        policy=PolicyConfiguration(granted_capabilities=("a", "b")),
    )
    equivalent = _configuration(
        policy=PolicyConfiguration(granted_capabilities=("a", "b")),
    )
    assert _with(ordered).fingerprint() == _with(equivalent).fingerprint()


def test_different_run_id_yields_same_fingerprint() -> None:
    configuration = _configuration()
    left = ResearchRunSpec(
        run_id="run-1:family",
        dataset_id=BASELINE.dataset_id,
        dataset_version=BASELINE.dataset_version,
        instrument_master_version=BASELINE.instrument_master_version,
        market_rule_version=BASELINE.market_rule_version,
        execution_model_version=BASELINE.execution_model_version,
        simulation_profile=BASELINE.simulation_profile,
        code_revision=BASELINE.code_revision,
        configuration_revision=BASELINE.configuration_revision,
        run_configuration=configuration,
    )
    right = replace(left, run_id="run-2:other-family")
    assert left.to_provenance().fingerprint() == right.to_provenance().fingerprint()


# --------------------------------------------------------------------------
# Fingerprint inequality for every material input
# --------------------------------------------------------------------------


def _fp(configuration: ResearchRunConfiguration) -> str:
    return _with(configuration).fingerprint()


@pytest.mark.parametrize(
    ("label", "configuration"),
    [
        ("strategy_id", _configuration(strategy=_strategy(strategy_id="ema"))),
        ("strategy_version", _configuration(strategy=_strategy(version="2"))),
        (
            "strategy_parameter",
            _configuration(strategy=_strategy(parameters=(("window", "50"),))),
        ),
        (
            "execution_model_id",
            _configuration(
                execution=_execution(
                    execution_models=(
                        SimulationModelIdentity(
                            model_id="QUOTE_X",
                            model_version="paper-core-v0.3",
                        ),
                    ),
                )
            ),
        ),
        (
            "execution_model_version",
            _configuration(
                execution=_execution(
                    execution_models=(
                        SimulationModelIdentity(model_id="QUOTE", model_version="paper-core-v0.9"),
                    ),
                )
            ),
        ),
        ("simulation_profile", _configuration(execution=_execution(profile_name="BASIC"))),
        ("latency_ms", _configuration(execution=_execution(latency_ms=100))),
        ("slippage_bps", _configuration(execution=_execution(slippage_bps=Decimal("5")))),
        (
            "slippage_model",
            _configuration(
                execution=_execution(
                    slippage_model=SimulationModelIdentity(
                        model_id=_SLIPPAGE.model_id,
                        model_version=_SLIPPAGE.model_version,
                        parameters=(("basis_points", "5"),),
                    ),
                )
            ),
        ),
        (
            "partial_fill_ratio",
            _configuration(execution=_execution(partial_fill_ratio=Decimal("0.5"))),
        ),
        ("fee_bps", _configuration(execution=_execution(fee_bps=Decimal("10")))),
        (
            "charge_model",
            _configuration(
                execution=_execution(
                    charge_model=SimulationModelIdentity(
                        model_id="paper.percentage_bps",
                        model_version="1",
                        parameters=(("component_name", "modeled_fee"), ("rate_bps", "10")),
                    ),
                )
            ),
        ),
        (
            "charge_model_rate",
            _configuration(
                execution=_execution(
                    charge_model=SimulationModelIdentity(
                        model_id="paper.percentage_bps",
                        model_version="1",
                        parameters=(("component_name", "modeled_fee"), ("rate_bps", "20")),
                    ),
                )
            ),
        ),
        (
            "volume_participation_rate",
            _configuration(execution=_execution(volume_participation_rate=Decimal("0.1"))),
        ),
        ("allow_incomplete", _configuration(allow_incomplete=True)),
        (
            "account_state_sampling_policy",
            _configuration(account_state_sampling_policy="AS_OF_OBSERVED"),
        ),
        (
            "broker_constraint",
            _configuration(
                broker_constraints=(
                    BrokerConstraintConfiguration(
                        name="lot",
                        minimum_quantity=Decimal("1"),
                    ),
                )
            ),
        ),
        (
            "starting_cash",
            _configuration(
                starting_capital=StartingCapitalConfiguration(
                    capital_source="backtest_configured",
                    currency="INR",
                    cash_balance=Decimal("2000"),
                    available_cash=Decimal("1000"),
                    blocked_cash=Decimal("0"),
                    margin_used=Decimal("0"),
                    margin_available=Decimal("1000"),
                    buying_power=Decimal("1000"),
                )
            ),
        ),
        (
            "available_cash",
            _configuration(
                starting_capital=StartingCapitalConfiguration(
                    capital_source="backtest_configured",
                    currency="INR",
                    cash_balance=Decimal("1000"),
                    available_cash=Decimal("900"),
                    blocked_cash=Decimal("0"),
                    margin_used=Decimal("0"),
                    margin_available=Decimal("1000"),
                    buying_power=Decimal("1000"),
                )
            ),
        ),
        (
            "margin_values",
            _configuration(
                starting_capital=StartingCapitalConfiguration(
                    capital_source="backtest_configured",
                    currency="INR",
                    cash_balance=Decimal("1000"),
                    available_cash=Decimal("1000"),
                    blocked_cash=Decimal("0"),
                    margin_used=Decimal("5"),
                    margin_available=Decimal("1000"),
                    buying_power=Decimal("1000"),
                )
            ),
        ),
        (
            "buying_power",
            _configuration(
                starting_capital=StartingCapitalConfiguration(
                    capital_source="backtest_configured",
                    currency="INR",
                    cash_balance=Decimal("1000"),
                    available_cash=Decimal("1000"),
                    blocked_cash=Decimal("0"),
                    margin_used=Decimal("0"),
                    margin_available=Decimal("1000"),
                    buying_power=Decimal("2000"),
                )
            ),
        ),
        (
            "policy_field",
            _configuration(
                policy=PolicyConfiguration(granted_capabilities=("trade.execute",)),
            ),
        ),
        (
            "policy_manual_approval",
            _configuration(policy=PolicyConfiguration(manual_approval=True)),
        ),
    ],
)
def test_material_configuration_change_changes_fingerprint(
    label: str,
    configuration: ResearchRunConfiguration,
) -> None:
    assert _fp(configuration) != _fp(_configuration()), label


def test_execution_model_count_change_changes_fingerprint() -> None:
    single = _execution(
        execution_models=(SimulationModelIdentity(model_id="QUOTE", model_version="v1"),),
    )
    both = _execution(
        execution_models=(
            SimulationModelIdentity(model_id="QUOTE", model_version="v1"),
            SimulationModelIdentity(model_id="BASIC_BAR", model_version="basic-bar-v4"),
        ),
    )
    assert _fp(_configuration(execution=single)) != _fp(_configuration(execution=both))


# --------------------------------------------------------------------------
# Decimal semantics
# --------------------------------------------------------------------------


def test_distinct_decimal_representations_remain_distinct() -> None:
    integral = _configuration(execution=_execution(fee_bps=Decimal("1")))
    scaled = _configuration(execution=_execution(fee_bps=Decimal("1.0")))
    assert _fp(integral) != _fp(scaled)


def test_none_is_distinct_from_zero() -> None:
    absent = _configuration(execution=_execution(volume_participation_rate=None))
    zero = _configuration(execution=_execution(volume_participation_rate=None))
    assert _fp(absent) == _fp(zero)
    present = _configuration(execution=_execution(fee_bps=None))
    explicit_zero = _configuration(execution=_execution(fee_bps=Decimal("0")))
    assert _fp(present) != _fp(explicit_zero)


# --------------------------------------------------------------------------
# Explicit exclusions
# --------------------------------------------------------------------------


def test_run_id_does_not_affect_provenance_fingerprint() -> None:
    configuration = _configuration()
    left = ResearchRunSpec(
        run_id="alpha",
        dataset_id=BASELINE.dataset_id,
        dataset_version=BASELINE.dataset_version,
        instrument_master_version=BASELINE.instrument_master_version,
        market_rule_version=BASELINE.market_rule_version,
        execution_model_version=BASELINE.execution_model_version,
        simulation_profile=BASELINE.simulation_profile,
        code_revision=BASELINE.code_revision,
        configuration_revision=BASELINE.configuration_revision,
        run_configuration=configuration,
    )
    right = replace(left, run_id="omega")
    assert left.to_provenance().fingerprint() == right.to_provenance().fingerprint()
    assert "run_id" not in left.to_provenance().canonical_payload()["extra"]  # type: ignore[operator]


def test_runtime_identity_is_absent_from_run_configuration() -> None:
    payload = _configuration().canonical_payload()
    serialized = repr(payload)
    assert "account_id" not in serialized
    assert "connection_id" not in serialized
    assert "run_id" not in serialized


# --------------------------------------------------------------------------
# Canonicalization and fail-closed rules
# --------------------------------------------------------------------------


def test_unsorted_strategy_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be sorted"):
        StrategyConfiguration(strategy_parameters=(("b", "2"), ("a", "1")))


def test_unsorted_model_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be sorted"):
        SimulationModelIdentity(
            model_id="m",
            model_version="1",
            parameters=(("b", "2"), ("a", "1")),
        )


def test_unsupported_scalar_type_fails_closed() -> None:
    from quantx.research.provenance import canonical_scalar

    with pytest.raises(TypeError, match="unsupported canonical provenance type"):
        canonical_scalar(object())


def test_run_configuration_exposes_no_fingerprint_api() -> None:
    configuration = _configuration()
    assert not hasattr(configuration, "fingerprint")
    assert not hasattr(configuration, "hash")


def test_provenance_without_run_configuration_keeps_legacy_payload() -> None:
    payload = BASELINE.canonical_payload()
    assert "run_configuration" not in payload


def test_charge_model_identity_matches_configured_model() -> None:
    model = PercentageBpsChargeModel(rate_bps=Decimal("10"))
    identity = SimulationModelIdentity(
        model_id=model.model_id,
        model_version=model.model_version,
        parameters=(("component_name", model.component_name), ("rate_bps", str(model.rate_bps))),
    )
    assert identity.canonical_payload()["parameters"] == [
        ["component_name", "modeled_fee"],
        ["rate_bps", "10"],
    ]


def test_duplicate_broker_constraint_names_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        ResearchRunConfiguration(
            broker_constraints=(
                BrokerConstraintConfiguration(name="lot"),
                BrokerConstraintConfiguration(name="lot"),
            ),
        )
