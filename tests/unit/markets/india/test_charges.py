from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quantx.execution.charges import ChargeBreakdown
from quantx.markets.india.domain import IndianExchange
from quantx.markets.india.charges import (
    IndiaChargeCalculationContext,
    IndiaChargeEvent,
    IndiaChargeIncidence,
    IndiaChargeInputUnavailable,
    IndiaChargePassThroughPolicy,
    IndiaChargeProduct,
    IndiaChargeRateSet,
    IndiaChargeRuleUnavailable,
    IndiaChargeSchedule,
    IndiaChargeScheduleEntry,
    IndiaMarketChargeModel,
    IndiaOptionType,
    IndiaRecoveryTaxTreatment,
    IndiaTradeSide,
)

D = Decimal
IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 1, 1, tzinfo=IST)
SPLIT = datetime(2026, 4, 1, tzinfo=IST)
SOURCE_NAMES = ("stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee", "gst")


def _sources() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (name, f"synthetic://india-charges/{name}", "synthetic-v1")
        for name in reversed(SOURCE_NAMES)
    )


def _rates(**overrides: Decimal | None) -> IndiaChargeRateSet:
    values: dict[str, Decimal | None] = {
        "stt_rate": D("0.001"),
        "stamp_duty_rate": D("0.00015"),
        "exchange_txn_rate": D("0.0001"),
        "ipft_rate": D("0.00001"),
        "sebi_turnover_rate": D("0.000001"),
        "gst_rate": D("0.18"),
    }
    values.update(overrides)
    return IndiaChargeRateSet(**values, component_sources=_sources())


def _policy(**overrides: IndiaChargeIncidence) -> IndiaChargePassThroughPolicy:
    values = {
        "stt": IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        "stamp_duty": IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        "exchange_txn": IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        "ipft": IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        "sebi_turnover_fee": IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        "version": "synthetic-billing-v1",
        "source_ref": "synthetic://billing-policy/v1",
    }
    values.update(overrides)
    return IndiaChargePassThroughPolicy(**values)


def _entry(
    product: IndiaChargeProduct = IndiaChargeProduct.EQUITY_DELIVERY,
    side: IndiaTradeSide = IndiaTradeSide.BUY,
    event: IndiaChargeEvent = IndiaChargeEvent.TRADE,
    rate_set: IndiaChargeRateSet | None = None,
    *,
    effective_from: datetime = START,
    effective_to: datetime | None = None,
) -> IndiaChargeScheduleEntry:
    return IndiaChargeScheduleEntry(
        effective_from=effective_from,
        effective_to=effective_to,
        version="synthetic-schedule-v1",
        rates=(((product, side, event), rate_set or _rates()),),
    )


def _model(*entries: IndiaChargeScheduleEntry) -> IndiaMarketChargeModel:
    return IndiaMarketChargeModel(IndiaChargeSchedule(tuple(entries)))


def _context(**overrides: object) -> IndiaChargeCalculationContext:
    values: dict[str, object] = {
        "transaction_value": D("10000"),
        "currency": "INR",
        "exchange": IndianExchange.NSE,
        "trade_side": IndiaTradeSide.BUY,
        "product": IndiaChargeProduct.EQUITY_DELIVERY,
        "event": IndiaChargeEvent.TRADE,
        "effective_at": datetime(2026, 3, 13, 10, 0, tzinfo=IST),
        "brokerage": D("0.50"),
        "dp_charges": D("0.25"),
        "other_taxable_service_charges": D("0.25"),
        "stt_gst_treatment": IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
        "stamp_duty_gst_treatment": IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
        "pass_through_policy": _policy(),
        "gst_policy_version": "synthetic-gst-policy-v1",
        "gst_policy_source_ref": "synthetic://gst-policy/v1",
    }
    values.update(overrides)
    return IndiaChargeCalculationContext(**values)  # type: ignore[arg-type]


def _amounts(result: ChargeBreakdown) -> dict[str, Decimal]:
    return {component.name: component.amount for component in result.components}


def test_delivery_trade_uses_transaction_value_and_returns_complete_breakdown() -> None:
    result = _model().calculate(_context())

    assert isinstance(result, ChargeBreakdown)
    assert result.model_id == "india.market_charges"
    assert result.model_version == "1"
    assert result.currency == "INR"
    assert _amounts(result) == {
        "stt": D("10.00"),
        "stamp_duty": D("1.50"),
        "exchange_txn": D("1.00"),
        "ipft": D("0.10"),
        "sebi_turnover_fee": D("0.01"),
        "gst": D("0.38"),
        "brokerage": D("0.50"),
        "dp_charges": D("0.25"),
        "other_taxable_service_charges": D("0.25"),
    }
    assert result.total == D("13.99")


def test_option_trade_uses_premium_not_underlying_transaction_value() -> None:
    model = _model(_entry(product=IndiaChargeProduct.EQUITY_OPTIONS))
    context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        transaction_value=D("999999"),
        premium_value=D("5000"),
    )

    result = model.calculate(context)

    assert _amounts(result)["stt"] == D("5.00")
    assert _amounts(result)["exchange_txn"] == D("0.50")


@pytest.mark.parametrize(
    ("option_type", "settlement_price", "strike", "expected_intrinsic"),
    [
        (IndiaOptionType.CALL, D("120"), D("100"), D("200")),
        (IndiaOptionType.PUT, D("80"), D("100"), D("200")),
        (IndiaOptionType.CALL, D("90"), D("100"), D("0")),
        (IndiaOptionType.PUT, D("110"), D("100"), D("0")),
    ],
)
def test_exercise_uses_intrinsic_for_stt_and_separate_notional_for_sebi(
    option_type: IndiaOptionType,
    settlement_price: Decimal,
    strike: Decimal,
    expected_intrinsic: Decimal,
) -> None:
    exercise_rates = _rates(
        stamp_duty_rate=D("0"),
        exchange_txn_rate=D("0"),
        ipft_rate=D("0"),
    )
    model = _model(
        _entry(
            product=IndiaChargeProduct.EQUITY_OPTIONS,
            event=IndiaChargeEvent.OPTION_EXERCISE,
            rate_set=exercise_rates,
        )
    )
    context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        option_type=option_type,
        quantity=D("10"),
        settlement_price=settlement_price,
        strike=strike,
        exercise_notional_value=D("50000"),
        stt_gst_treatment=IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE,
    )

    result = model.calculate(context)

    assert _amounts(result)["stt"] == (expected_intrinsic * D("0.001")).quantize(D("0.01"))
    assert _amounts(result)["sebi_turnover_fee"] == D("0.05")
    assert _amounts(result)["stamp_duty"] == D("0")
    assert _amounts(result)["exchange_txn"] == D("0")
    assert _amounts(result)["ipft"] == D("0")


def test_option_assignment_fails_closed() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="OPTION_ASSIGNMENT is unsupported"):
        _model().calculate(_context(event=IndiaChargeEvent.OPTION_ASSIGNMENT))


def test_option_exercise_requires_buyer_side() -> None:
    model = _model(
        _entry(
            product=IndiaChargeProduct.EQUITY_OPTIONS,
            side=IndiaTradeSide.SELL,
            event=IndiaChargeEvent.OPTION_EXERCISE,
            rate_set=_rates(
                stamp_duty_rate=D("0"),
                exchange_txn_rate=D("0"),
                ipft_rate=D("0"),
            ),
        )
    )
    context = _context(
        trade_side=IndiaTradeSide.SELL,
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        option_type=IndiaOptionType.CALL,
        quantity=D("1"),
        settlement_price=D("100"),
        strike=D("90"),
        exercise_notional_value=D("1000"),
    )
    with pytest.raises(IndiaChargeRuleUnavailable, match="exercising purchaser"):
        model.calculate(context)


def test_exercise_nonzero_unsupported_component_basis_fails_closed() -> None:
    model = _model(
        _entry(
            product=IndiaChargeProduct.EQUITY_OPTIONS,
            event=IndiaChargeEvent.OPTION_EXERCISE,
            rate_set=_rates(exchange_txn_rate=D("0.0001")),
        )
    )
    context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        option_type=IndiaOptionType.CALL,
        quantity=D("1"),
        settlement_price=D("100"),
        strike=D("90"),
        exercise_notional_value=D("1000"),
    )
    with pytest.raises(IndiaChargeRuleUnavailable, match="exercise basis is unsupported"):
        model.calculate(context)


def test_sell_side_stamp_duty_requires_explicit_sourced_zero() -> None:
    model = _model(
        _entry(side=IndiaTradeSide.SELL, rate_set=_rates(stamp_duty_rate=D("0.00015")))
    )
    with pytest.raises(IndiaChargeRuleUnavailable, match="explicit zero rule"):
        model.calculate(_context(trade_side=IndiaTradeSide.SELL))


def test_sell_side_stamp_duty_accepts_explicit_zero_rule() -> None:
    model = _model(_entry(side=IndiaTradeSide.SELL, rate_set=_rates(stamp_duty_rate=D("0"))))
    assert _amounts(model.calculate(_context(trade_side=IndiaTradeSide.SELL)))["stamp_duty"] == D("0")


def test_not_applicable_incidence_requires_explicit_zero_rate() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="NOT_APPLICABLE requires"):
        _model().calculate(
            _context(pass_through_policy=_policy(stt=IndiaChargeIncidence.NOT_APPLICABLE))
        )


def test_broker_absorbed_components_do_not_enter_client_total_or_gst_base() -> None:
    absorbed = IndiaChargeIncidence.BROKER_ABSORBED
    policy = _policy(
        stt=absorbed,
        stamp_duty=absorbed,
        exchange_txn=absorbed,
        ipft=absorbed,
        sebi_turnover_fee=absorbed,
    )
    result = _model().calculate(_context(pass_through_policy=policy))

    amounts = _amounts(result)
    assert all(amounts[name] == D("0") for name in _SOURCE_NAMES[:-1])
    assert amounts["gst"] == D("0.18")
    assert result.total == D("1.18")


def test_gst_requires_all_caller_supplied_service_inputs() -> None:
    with pytest.raises(IndiaChargeInputUnavailable, match="complete brokerage"):
        _model().calculate(_context(brokerage=None))


def test_gst_requires_both_recovery_treatments_and_policy_identity() -> None:
    with pytest.raises(IndiaChargeInputUnavailable, match="GST treatment"):
        _model().calculate(_context(stt_gst_treatment=None))
    with pytest.raises(ValueError, match="GST policy version"):
        _model().calculate(_context(gst_policy_version=" "))


def test_missing_pass_through_policy_fails_closed() -> None:
    with pytest.raises(IndiaChargeInputUnavailable, match="pass-through policy"):
        _model().calculate(_context(pass_through_policy=None))


def test_missing_component_rate_is_not_converted_to_zero() -> None:
    model = _model(_entry(rate_set=_rates(stt_rate=None)))
    with pytest.raises(IndiaChargeRuleUnavailable, match="stt rate is unavailable"):
        model.calculate(_context())


def test_missing_product_side_event_mapping_fails_closed() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="no sourced rule"):
        _model().calculate(_context(product=IndiaChargeProduct.EQUITY_FUTURES))


def test_unsupported_exchange_and_currency_fail_closed() -> None:
    model = _model()
    with pytest.raises(IndiaChargeRuleUnavailable, match="only NSE"):
        model.calculate(_context(exchange=IndianExchange.BSE))
    with pytest.raises(IndiaChargeInputUnavailable, match="currency must be INR"):
        model.calculate(_context(currency="USD"))


def test_missing_effective_schedule_coverage_fails_closed() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="no charge schedule covers"):
        _model().calculate(
            _context(effective_at=datetime(2025, 12, 31, 23, 59, tzinfo=IST))
        )


def test_schedule_selection_uses_inclusive_start_and_exclusive_end() -> None:
    first = _entry(effective_from=START, effective_to=SPLIT)
    second = _entry(effective_from=SPLIT)
    schedule = IndiaChargeSchedule((first, second))
    before = datetime(2026, 3, 31, 18, 29, 59, tzinfo=timezone.utc)
    at = datetime(2026, 3, 31, 18, 30, tzinfo=timezone.utc)

    assert schedule.select(before) == first
    assert schedule.select(at) == second


def test_schedule_gaps_are_not_bridged() -> None:
    first = _entry(
        effective_from=START,
        effective_to=datetime(2026, 3, 1, tzinfo=IST),
    )
    second = _entry(effective_from=SPLIT)
    schedule = IndiaChargeSchedule((first, second))
    with pytest.raises(IndiaChargeRuleUnavailable, match="no charge schedule covers"):
        schedule.select(datetime(2026, 3, 15, tzinfo=IST))


def test_overlapping_schedule_entries_are_rejected() -> None:
    first = _entry(effective_from=START, effective_to=datetime(2026, 5, 1, tzinfo=IST))
    second = _entry(effective_from=SPLIT)
    with pytest.raises(ValueError, match="must not overlap"):
        IndiaChargeSchedule((first, second))


def test_schedule_boundaries_must_be_ist_midnight_instants() -> None:
    with pytest.raises(ValueError, match="Asia/Kolkata midnight"):
        _entry(effective_from=datetime(2026, 1, 1, 9, 15, tzinfo=IST))


def test_schedule_rate_keys_are_unique_and_sorted() -> None:
    delivery = _rates()
    options = _rates()
    entry = IndiaChargeScheduleEntry(
        effective_from=START,
        effective_to=None,
        version="synthetic",
        rates=(
            ((IndiaChargeProduct.EQUITY_OPTIONS, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE), options),
            ((IndiaChargeProduct.EQUITY_DELIVERY, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE), delivery),
        ),
    )
    assert tuple(key[0] for key, _ in entry.rates) == (
        IndiaChargeProduct.EQUITY_DELIVERY,
        IndiaChargeProduct.EQUITY_OPTIONS,
    )


def test_duplicate_schedule_rate_keys_are_rejected() -> None:
    rate_set = _rates()
    key = (IndiaChargeProduct.EQUITY_DELIVERY, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE)
    with pytest.raises(ValueError, match="must be unique"):
        IndiaChargeScheduleEntry(
            effective_from=START,
            effective_to=None,
            version="synthetic",
            rates=((key, rate_set), (key, rate_set)),
        )


def test_every_component_requires_source_even_when_rate_is_zero() -> None:
    with pytest.raises(ValueError, match="requires source/version evidence"):
        IndiaChargeRateSet(
            stt_rate=D("0"),
            stamp_duty_rate=D("0"),
            exchange_txn_rate=D("0"),
            ipft_rate=D("0"),
            sebi_turnover_rate=D("0"),
            gst_rate=D("0"),
            component_sources=_sources()[:-1],
        )


def test_source_metadata_is_sorted_and_unique() -> None:
    rate_set = _rates()
    assert tuple(item[0] for item in rate_set.component_sources) == tuple(sorted(SOURCE_NAMES))
    with pytest.raises(ValueError, match="source names must be unique"):
        IndiaChargeRateSet(
            stt_rate=D("0"),
            stamp_duty_rate=D("0"),
            exchange_txn_rate=D("0"),
            ipft_rate=D("0"),
            sebi_turnover_rate=D("0"),
            gst_rate=D("0"),
            component_sources=_sources() + (_sources()[0],),
        )


@pytest.mark.parametrize("invalid", [D("NaN"), D("Infinity"), D("-0.1")])
def test_rates_reject_non_finite_or_negative_values(invalid: Decimal) -> None:
    with pytest.raises(ValueError):
        _rates(stt_rate=invalid)


def test_context_rejects_non_decimal_and_non_finite_amounts() -> None:
    with pytest.raises(TypeError, match="transaction_value must be a Decimal"):
        _context(transaction_value=1000)
    with pytest.raises(ValueError, match="premium_value must be finite"):
        _context(product=IndiaChargeProduct.EQUITY_OPTIONS, premium_value=D("NaN"))


def test_context_rejects_naive_effective_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _context(effective_at=datetime(2026, 3, 13, 10, 0))


def test_context_rejects_inconsistent_option_exercise_fields() -> None:
    with pytest.raises(ValueError, match="only valid for OPTION_EXERCISE"):
        _context(option_type=IndiaOptionType.CALL)


def test_exercise_requires_positive_quantity_and_strike() -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        _context(
            event=IndiaChargeEvent.OPTION_EXERCISE,
            product=IndiaChargeProduct.EQUITY_OPTIONS,
            quantity=D("0"),
        )
    with pytest.raises(ValueError, match="strike must be positive"):
        _context(
            event=IndiaChargeEvent.OPTION_EXERCISE,
            product=IndiaChargeProduct.EQUITY_OPTIONS,
            strike=D("0"),
        )


def test_rounding_is_half_up_per_component() -> None:
    model = _model(
        _entry(
            rate_set=_rates(
                stt_rate=D("0.000005"),
                stamp_duty_rate=D("0"),
                exchange_txn_rate=D("0"),
                ipft_rate=D("0"),
                sebi_turnover_rate=D("0"),
                gst_rate=D("0"),
            )
        )
    )
    context = _context(
        transaction_value=D("1000"),
        brokerage=D("0"),
        dp_charges=D("0"),
        other_taxable_service_charges=D("0"),
    )
    result = model.calculate(context)
    assert _amounts(result)["stt"] == D("0.01")
    assert _amounts(result)["gst"] == D("0.00")


def test_breakdown_provenance_retains_schedule_component_and_policy_versions() -> None:
    result = _model().calculate(_context())
    assert "schedule:synthetic-schedule-v1" in result.provenance
    assert "component:stt:synthetic-v1:synthetic://india-charges/stt" in result.provenance
    assert "pass_through_policy:synthetic-billing-v1:synthetic://billing-policy/v1" in result.provenance
    assert "gst_policy:synthetic-gst-policy-v1:synthetic://gst-policy/v1" in result.provenance
