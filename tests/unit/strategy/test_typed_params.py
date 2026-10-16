from decimal import Decimal

import pytest

from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.typed_params import TypedParams


def test_integer_getter_accepts_canonical_signed_integers_and_bounds() -> None:
    params = TypedParams((("max_bars", "512"), ("offset", "-12"), ("zero", "0")))

    assert params.get_int("zero", minimum=0, maximum=512) == 0
    assert params.get_int("max_bars", minimum=0, maximum=512) == 512
    assert params.get_int("offset") == -12


@pytest.mark.parametrize("value", ["+1", "01", "-0", " 1", "1 ", "1.0", "1e2", "１２"])
def test_integer_getter_rejects_noncanonical_lexemes(value: str) -> None:
    with pytest.raises(ValueError, match="history_bars"):
        TypedParams((("history_bars", value),)).get_int("history_bars")


def test_history_bars_range_errors_name_the_field() -> None:
    with pytest.raises(ValueError, match="history_bars"):
        TypedParams((("history_bars", "513"),)).get_int("history_bars", minimum=0, maximum=512)
    with pytest.raises(ValueError, match="history_bars"):
        TypedParams((("history_bars", "-1"),)).get_int("history_bars", minimum=0, maximum=512)


def test_from_ir_reuses_canonical_parameter_tuple_and_exact_spelling() -> None:
    ir = StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"),
            "1",
            "Buy and Hold",
            parameters={"price": "-12.3400"},
        )
    )

    params = TypedParams.from_ir(ir)

    assert params.parameters is ir.parameters
    assert params.get_decimal("price") == Decimal("-12.3400")
    assert ir.parameters == (("price", "-12.3400"),)


def test_decimal_getter_accepts_canonical_fixed_point_without_normalizing_ir() -> None:
    raw = "-12.3400"
    params = TypedParams((("price", raw),))
    assert params.get_decimal("price") == Decimal(raw)
    assert params.parameters == (("price", raw),)


@pytest.mark.parametrize(
    "value",
    ["+1", "01", "01.2", " 1", "1 ", "1e2", "NaN", "Infinity", "-Infinity", "-0", "-0.0"],
)
def test_decimal_getter_rejects_noncanonical_lexemes(value: str) -> None:
    with pytest.raises(ValueError, match="price"):
        TypedParams((("price", value),)).get_decimal("price")


def test_boolean_and_string_getters_are_strict_and_lossless() -> None:
    params = TypedParams((("enabled", "true"), ("label", "  Exact text  ")))
    assert params.get_bool("enabled") is True
    assert params.get_string("label") == "  Exact text  "
    with pytest.raises(ValueError, match="switch"):
        TypedParams((("switch", "True"),)).get_bool("switch")


def test_missing_required_values_fail_but_explicit_defaults_work() -> None:
    params = TypedParams(())
    with pytest.raises(ValueError, match="quantity"):
        params.get_int("quantity")
    assert params.get_int("quantity", default=3, minimum=0) == 3
