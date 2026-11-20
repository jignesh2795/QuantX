from decimal import Decimal, ROUND_HALF_EVEN, localcontext

import pytest

from quantx.domain.enums import OrderSide
from quantx.execution.charges import (
    ChargeBase,
    ChargeCalculationContext,
    ChargeSide,
    CostLine,
    CostSchedule,
    CostScheduleChargeModel,
)


def _model(
    *lines: CostLine,
    currency: str = "INR",
    digits: int = 2,
) -> CostScheduleChargeModel:
    return CostScheduleChargeModel(
        CostSchedule(
            lines=tuple(lines),
            currency=currency,
            digits=digits,
            source="caller-supplied-test",
        )
    )


def _context(
    *,
    side: OrderSide = OrderSide.BUY,
    price: str = "100",
    quantity: str = "2",
    currency: str = "INR",
) -> ChargeCalculationContext:
    unit_price = Decimal(price)
    units = Decimal(quantity)
    return ChargeCalculationContext(
        transaction_value=unit_price * units,
        currency=currency,
        side=side,
        unit_price=unit_price,
        quantity=units,
    )


def test_all_four_bases_use_base_dependent_rate_units() -> None:
    result = _model(
        CostLine("turnover", ChargeBase.TURNOVER, Decimal("0.001")),
        CostLine("units", ChargeBase.UNITS, Decimal("0.50")),
        CostLine("order", ChargeBase.ORDER, Decimal("3")),
        CostLine(
            "tax",
            ChargeBase.CHARGES,
            Decimal("0.18"),
            of=("turnover", "units"),
        ),
    ).calculate(_context())

    amounts = {component.name: component.amount for component in result.components}
    assert amounts == {
        "order": Decimal("3"),
        "tax": Decimal("0.216"),
        "turnover": Decimal("0.200"),
        "units": Decimal("1.00"),
    }
    assert result.total == Decimal("4.416")
    assert result.rounded_total == Decimal("4.42")
    assert result.applied_total == Decimal("4.42")


def test_minimum_and_maximum_clamp_raw_line_before_dependency() -> None:
    result = _model(
        CostLine(
            "brokerage",
            ChargeBase.TURNOVER,
            Decimal("0.001"),
            minimum=Decimal("0.50"),
            maximum=Decimal("0.75"),
        ),
        CostLine(
            "tax",
            ChargeBase.CHARGES,
            Decimal("0.18"),
            of=("brokerage",),
        ),
    ).calculate(_context())

    amounts = {component.name: component.amount for component in result.components}
    assert amounts["brokerage"] == Decimal("0.50")
    assert amounts["tax"] == Decimal("0.0900")
    assert result.total == Decimal("0.5900")
    assert result.rounded_total == Decimal("0.59")


def test_side_filtered_dependency_contributes_zero_and_is_omitted() -> None:
    model = _model(
        CostLine("brokerage", ChargeBase.ORDER, Decimal("2")),
        CostLine("sell_levy", ChargeBase.TURNOVER, Decimal("0.01"), side=ChargeSide.SELL),
        CostLine(
            "tax",
            ChargeBase.CHARGES,
            Decimal("0.18"),
            of=("brokerage", "sell_levy"),
        ),
    )

    buy = model.calculate(_context(side=OrderSide.BUY))
    sell = model.calculate(_context(side=OrderSide.SELL))

    buy_amounts = {component.name: component.amount for component in buy.components}
    sell_amounts = {component.name: component.amount for component in sell.components}
    assert "sell_levy" not in buy_amounts
    assert buy_amounts["tax"] == Decimal("0.36")
    assert sell_amounts["sell_levy"] == Decimal("2.00")
    assert sell_amounts["tax"] == Decimal("0.7200")


def test_order_base_is_a_fixed_amount_per_fill() -> None:
    model = _model(CostLine("per_fill", ChargeBase.ORDER, Decimal("20")))
    first = model.calculate(_context(quantity="1"))
    second = model.calculate(_context(quantity="4", price="150"))

    assert first.total == Decimal("20")
    assert second.total == Decimal("20")
    assert first.rounded_total == Decimal("20.00")
    assert second.rounded_total == Decimal("20.00")


def test_half_even_rounding_is_applied_once_to_each_fill() -> None:
    model = _model(CostLine("per_fill", ChargeBase.ORDER, Decimal("0.005")))
    first = model.calculate(_context())
    second = model.calculate(_context(quantity="3", price="75"))

    assert first.total == Decimal("0.005")
    assert second.total == Decimal("0.005")
    assert first.rounded_total == Decimal("0.00")
    assert second.rounded_total == Decimal("0.00")
    assert first.rounded_total + second.rounded_total == Decimal("0.00")


def test_half_even_rounding_uses_schedule_digits() -> None:
    model = _model(
        CostLine("per_fill", ChargeBase.ORDER, Decimal("0.015")),
    )
    result = model.calculate(_context())
    assert result.rounded_total == Decimal("0.02")


def test_zero_valued_applicable_line_is_retained() -> None:
    result = _model(
        CostLine("zero_fee", ChargeBase.TURNOVER, Decimal("0")),
    ).calculate(_context())
    assert result.components[0].name == "zero_fee"
    assert result.components[0].amount == Decimal("0")
    assert result.rounded_total == Decimal("0.00")


def test_cost_schedule_identity_is_order_independent_and_parameter_complete() -> None:
    first = _model(
        CostLine("a", ChargeBase.TURNOVER, Decimal("0.01")),
        CostLine("b", ChargeBase.UNITS, Decimal("2")),
    )
    reordered = _model(
        CostLine("b", ChargeBase.UNITS, Decimal("2")),
        CostLine("a", ChargeBase.TURNOVER, Decimal("0.01")),
    )
    changed = _model(
        CostLine("a", ChargeBase.TURNOVER, Decimal("0.0101")),
        CostLine("b", ChargeBase.UNITS, Decimal("2")),
    )

    assert first.model_id == reordered.model_id
    assert first.schedule.material_parameters == reordered.schedule.material_parameters
    assert first.model_id != changed.model_id
    assert ("rounding", "ROUND_HALF_EVEN") in first.schedule.material_parameters
    assert ("source", "caller-supplied-test") in first.schedule.material_parameters


def test_cost_schedule_dependencies_are_evaluated_in_stable_topological_order() -> None:
    schedule = CostSchedule(
        lines=(
            CostLine("z_tax", ChargeBase.CHARGES, Decimal("0.18"), of=("b_fee",)),
            CostLine("b_fee", ChargeBase.TURNOVER, Decimal("0.01")),
            CostLine("a_fee", ChargeBase.ORDER, Decimal("1")),
        ),
        currency="INR",
        digits=2,
        source="test",
    )
    assert schedule.evaluation_order == ("a_fee", "b_fee", "z_tax")


@pytest.mark.parametrize(
    "lines",
    [
        (
            CostLine("a", ChargeBase.CHARGES, Decimal("0.1"), of=("missing",)),
        ),
        (
            CostLine("a", ChargeBase.CHARGES, Decimal("0.1"), of=("b",)),
            CostLine("b", ChargeBase.CHARGES, Decimal("0.1"), of=("a",)),
        ),
        (
            CostLine("a", ChargeBase.CHARGES, Decimal("0.1"), of=("a",)),
        ),
    ],
)
def test_missing_or_cyclic_dependencies_are_rejected(lines: tuple[CostLine, ...]) -> None:
    with pytest.raises(ValueError):
        CostSchedule(lines=lines, currency="INR", digits=2, source="test")


def test_duplicate_dependencies_are_rejected() -> None:
    with pytest.raises(ValueError, match="references must be unique"):
        CostLine(
            "tax",
            ChargeBase.CHARGES,
            Decimal("0.18"),
            of=("brokerage", "brokerage"),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate": Decimal("-0.1")},
        {"rate": Decimal("NaN")},
        {"rate": Decimal("Infinity")},
        {"minimum": Decimal("-0.1")},
        {"maximum": Decimal("-0.1")},
    ],
)
def test_cost_line_rejects_negative_or_non_finite_values(kwargs: dict[str, Decimal]) -> None:
    values = {"name": "fee", "base": ChargeBase.TURNOVER, "rate": Decimal("0.01")}
    values.update(kwargs)
    with pytest.raises(ValueError):
        CostLine(**values)  # type: ignore[arg-type]


def test_minimum_cannot_exceed_maximum() -> None:
    with pytest.raises(ValueError, match="minimum cannot exceed maximum"):
        CostLine(
            "fee",
            ChargeBase.TURNOVER,
            Decimal("0.01"),
            minimum=Decimal("2"),
            maximum=Decimal("1"),
        )


def test_schedule_requires_currency_digits_source_and_lines() -> None:
    with pytest.raises(ValueError, match="at least one line"):
        CostSchedule((), "INR", 2, "test")
    with pytest.raises(ValueError, match="currency"):
        CostSchedule(
            (CostLine("fee", ChargeBase.ORDER, Decimal("1")),),
            " ",
            2,
            "test",
        )
    with pytest.raises(ValueError, match="between 0 and 18"):
        CostSchedule(
            (CostLine("fee", ChargeBase.ORDER, Decimal("1")),),
            "INR",
            19,
            "test",
        )


def test_schedule_rejects_context_currency_and_notional_mismatch() -> None:
    model = _model(CostLine("fee", ChargeBase.TURNOVER, Decimal("0.01")))
    with pytest.raises(ValueError, match="does not match"):
        model.calculate(_context(currency="USD"))
    with pytest.raises(ValueError, match="must equal"):
        model.calculate(
            ChargeCalculationContext(
                transaction_value=Decimal("199"),
                currency="INR",
                side=OrderSide.BUY,
                unit_price=Decimal("100"),
                quantity=Decimal("2"),
            )
        )


def test_schedule_requires_complete_fill_context() -> None:
    model = _model(CostLine("fee", ChargeBase.TURNOVER, Decimal("0.01")))
    with pytest.raises(ValueError, match="requires side"):
        model.calculate(ChargeCalculationContext(transaction_value=Decimal("200"), currency="INR"))


def test_schedule_calculation_preserves_decimal_precision_beyond_default_context() -> None:
    price = Decimal("12345678901234567890.12345678901234567890")
    quantity = Decimal("3.0000000000000000001")
    rate = Decimal("0.0000000000000000001234567890123456789")
    with localcontext() as context:
        context.prec = 100
        notional = price * quantity
        expected = notional * rate

    result = _model(
        CostLine("turnover", ChargeBase.TURNOVER, rate),
        digits=18,
    ).calculate(
        ChargeCalculationContext(
            transaction_value=notional,
            currency="INR",
            side=OrderSide.BUY,
            unit_price=price,
            quantity=quantity,
        )
    )

    with localcontext() as context:
        context.prec = 100
        expected_rounded = expected.quantize(
            Decimal("0.000000000000000001"),
            rounding=ROUND_HALF_EVEN,
        )
    assert result.total == expected
    assert result.rounded_total == expected_rounded


def test_breakdown_total_sums_multiple_high_precision_components_exactly() -> None:
    rates = (
        Decimal("0.123456789012345678901234567890123456789"),
        Decimal("0.987654321098765432109876543210987654321"),
    )
    with localcontext() as context:
        context.prec = 100
        expected = Decimal("100") * rates[0] + Decimal("100") * rates[1]

    result = _model(
        CostLine("first", ChargeBase.TURNOVER, rates[0]),
        CostLine("second", ChargeBase.TURNOVER, rates[1]),
    ).calculate(_context(price="100", quantity="1"))

    assert result.total == expected
