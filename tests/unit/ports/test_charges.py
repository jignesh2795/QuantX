"""Neutral transaction-charge contract ownership regressions."""

from decimal import Decimal

import pytest

import quantx.execution.charges as execution_charges
import quantx.ports.charges as canonical_charges


def test_charge_contracts_are_canonical_in_ports_and_legacy_identity_is_preserved() -> None:
    names = (
        "ChargeCalculationContext",
        "ChargeComponent",
        "ChargeBreakdown",
        "ChargeModel",
    )
    for name in names:
        contract = getattr(canonical_charges, name)
        assert contract.__module__ == "quantx.ports.charges"
        assert getattr(execution_charges, name) is contract
        assert name in canonical_charges.__all__
        assert name in execution_charges.__all__


def test_percentage_basis_points_model_remains_execution_owned() -> None:
    model = execution_charges.PercentageBpsChargeModel
    assert model.__module__ == "quantx.execution.charges"
    assert "PercentageBpsChargeModel" in execution_charges.__all__
    assert not hasattr(canonical_charges, "PercentageBpsChargeModel")


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_neutral_charge_context_rejects_non_finite_transaction_value(value: Decimal) -> None:
    with pytest.raises(ValueError, match="transaction_value must be finite"):
        canonical_charges.ChargeCalculationContext(transaction_value=value)


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_neutral_charge_component_rejects_non_finite_amount(value: Decimal) -> None:
    with pytest.raises(ValueError, match="charge component amount must be finite"):
        canonical_charges.ChargeComponent("fee", value)
