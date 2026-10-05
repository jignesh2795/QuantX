from decimal import Decimal

import pytest

from quantx.execution.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
    PercentageBpsChargeModel,
)


def test_percentage_bps_charge_is_deterministic() -> None:
    model = PercentageBpsChargeModel(
        rate_bps=Decimal("10"),
        component_name="brokerage",
        model_id="test.model",
        model_version="3",
        provenance=("configured_test",),
    )
    context = ChargeCalculationContext(
        transaction_value=Decimal("1000"),
        currency="INR",
    )

    first = model.calculate(context)
    second = model.calculate(context)

    assert first == second
    assert first.total == Decimal("1")
    assert first.currency == "INR"
    assert first.components == (ChargeComponent("brokerage", Decimal("1")),)
    assert first.model_id == "test.model"
    assert first.model_version == "3"
    assert first.provenance == ("configured_test",)


def test_charge_breakdown_sums_components_exactly() -> None:
    breakdown = ChargeBreakdown(
        currency="INR",
        components=(
            ChargeComponent("brokerage", Decimal("1.10")),
            ChargeComponent("exchange", Decimal("0.40")),
            ChargeComponent("tax", Decimal("0.50")),
        ),
        model_id="composite.test",
        model_version="1",
        provenance=("explicit_test_configuration",),
    )

    assert breakdown.total == Decimal("2.00")


def test_charge_component_names_must_be_unique() -> None:
    with pytest.raises(ValueError, match="names must be unique"):
        ChargeBreakdown(
            currency="INR",
            components=(
                ChargeComponent("brokerage", Decimal("1")),
                ChargeComponent("brokerage", Decimal("2")),
            ),
            model_id="test",
            model_version="1",
        )


def test_charge_contract_rejects_non_decimal_amounts() -> None:
    with pytest.raises(TypeError, match="transaction_value must be a Decimal"):
        ChargeCalculationContext(transaction_value=1000)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="rate_bps must be a Decimal"):
        PercentageBpsChargeModel(rate_bps=10)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="charge component amount must be a Decimal"):
        ChargeComponent("brokerage", 1)  # type: ignore[arg-type]


def test_percentage_bps_charge_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="rate_bps cannot be negative"):
        PercentageBpsChargeModel(rate_bps=Decimal("-1"))


def test_zero_rate_is_explicitly_zero() -> None:
    model = PercentageBpsChargeModel(rate_bps=Decimal("0"))
    result = model.calculate(
        ChargeCalculationContext(transaction_value=Decimal("1000"))
    )

    assert result.total == Decimal("0")
    assert result.components[0] == ChargeComponent("modeled_fee", Decimal("0"))

