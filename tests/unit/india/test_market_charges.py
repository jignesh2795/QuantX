from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import quantx.india.charges as india_charges
from quantx.india.charges import (
    IndiaChargeBasis,
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
from quantx.india.domain import IndianExchange

IST = ZoneInfo("Asia/Kolkata")


def _policy() -> IndiaChargePassThroughPolicy:
    return IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        stamp_duty=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="policy-v1",
        source_ref="policy-source",
    )


def _rates() -> IndiaChargeRateSet:
    return IndiaChargeRateSet(
        stt_rate=Decimal("0.001"),
        stamp_duty_rate=Decimal("0.00015"),
        exchange_txn_rate=Decimal("0.0000297"),
        ipft_rate=Decimal("0.000001"),
        sebi_turnover_rate=Decimal("0.000001"),
        gst_rate=Decimal("0.18"),
        component_sources=(
            ("stt", "stt-source", "stt-v1"),
            ("stamp_duty", "stamp-source", "stamp-v1"),
            ("exchange_txn", "exchange-source", "exchange-v1"),
            ("ipft", "ipft-source", "ipft-v1"),
            ("sebi_turnover_fee", "sebi-source", "sebi-v1"),
            ("gst", "gst-source", "gst-v1"),
        ),
        component_bases=(
            ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
            ("stamp_duty", IndiaChargeBasis.TRANSACTION_VALUE),
            ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
            ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
            ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
            ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
        ),
    )


def _schedule() -> IndiaChargeSchedule:
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="schedule-v1",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): _rates()
        },
    )
    return IndiaChargeSchedule((entry,))


def _context(**overrides) -> IndiaChargeCalculationContext:
    values = {
        "transaction_value": Decimal("10000"),
        "currency": "INR",
        "exchange": IndianExchange.NSE,
        "trade_side": IndiaTradeSide.BUY,
        "product": IndiaChargeProduct.EQUITY_DELIVERY,
        "event": IndiaChargeEvent.TRADE,
        "effective_at": datetime(2026, 4, 1, tzinfo=IST),
        "brokerage": Decimal("10"),
        "dp_charges": Decimal("2"),
        "other_taxable_service_charges": Decimal("0"),
        "stt_gst_treatment": IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE,
        "stamp_duty_gst_treatment": IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
        "pass_through_policy": _policy(),
        "gst_policy_version": "gst-policy-v1",
        "gst_policy_source_ref": "gst-policy-source",
    }
    values.update(overrides)
    return IndiaChargeCalculationContext(**values)


def test_model_has_charge_model_interface() -> None:
    model = IndiaMarketChargeModel(schedule=_schedule())

    assert hasattr(model, "model_id")
    assert hasattr(model, "model_version")
    assert callable(model.calculate)


def test_effective_utc_and_ist_select_same_entry() -> None:
    schedule = _schedule()
    ist_instant = datetime(2026, 4, 1, 0, 0, tzinfo=IST)
    utc_instant = ist_instant.astimezone(UTC)

    assert schedule.select(ist_instant) is schedule.select(utc_instant)


def test_effective_from_inclusive_and_effective_to_exclusive() -> None:
    first_rates = _rates()
    second_rates = _rates()
    first = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=datetime(2026, 4, 1, tzinfo=IST),
        version="first",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): first_rates
        },
    )
    second = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 4, 1, tzinfo=IST),
        effective_to=None,
        version="second",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): second_rates
        },
    )
    schedule = IndiaChargeSchedule((first, second))

    assert schedule.select(datetime(2026, 4, 1, tzinfo=IST)).version == "second"
    assert schedule.select(datetime(2026, 3, 31, 23, 59, tzinfo=IST)).version == "first"


def test_overlapping_schedule_rejected() -> None:
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="entry",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): _rates()
        },
    )
    with pytest.raises(ValueError, match="overlap"):
        IndiaChargeSchedule((entry, entry))


def test_schedule_gap_is_unavailable() -> None:
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=datetime(2026, 2, 1, tzinfo=IST),
        version="entry",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): _rates()
        },
    )
    schedule = IndiaChargeSchedule((entry,))

    with pytest.raises(IndiaChargeRuleUnavailable):
        schedule.select(datetime(2026, 3, 1, tzinfo=IST))


def test_missing_rate_raises_rule_unavailable() -> None:
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="entry",
        rates={
            (
                IndiaChargeProduct.EQUITY_DELIVERY,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.TRADE,
            ): IndiaChargeRateSet(
                stt_rate=None,
                stamp_duty_rate=Decimal("0"),
                exchange_txn_rate=Decimal("0"),
                ipft_rate=Decimal("0"),
                sebi_turnover_rate=Decimal("0"),
                gst_rate=Decimal("0"),
                component_sources=(
                    ("stamp_duty", "s", "v"),
                    ("exchange_txn", "s", "v"),
                    ("ipft", "s", "v"),
                    ("sebi_turnover_fee", "s", "v"),
                    ("gst", "s", "v"),
                ),
                component_bases=(
                    ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
                    ("stamp_duty", IndiaChargeBasis.TRANSACTION_VALUE),
                    ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
                    ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
                    ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
                    ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
                ),
            )
        },
    )
    model = IndiaMarketChargeModel(schedule=IndiaChargeSchedule((entry,)))

    with pytest.raises(IndiaChargeRuleUnavailable, match="missing India charge rate"):
        model.calculate(_context())


def test_missing_source_for_zero_rate_rejected_at_construction() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="missing source"):
        IndiaChargeRateSet(
            stt_rate=Decimal("0"),
            stamp_duty_rate=Decimal("0"),
            exchange_txn_rate=Decimal("0"),
            ipft_rate=Decimal("0"),
            sebi_turnover_rate=Decimal("0"),
            gst_rate=Decimal("0"),
            component_sources=(
                ("stamp_duty", "s", "v"),
                ("exchange_txn", "s", "v"),
                ("ipft", "s", "v"),
                ("sebi_turnover_fee", "s", "v"),
                ("gst", "s", "v"),
            ),
            component_bases=(
                ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
                ("stamp_duty", IndiaChargeBasis.TRANSACTION_VALUE),
                ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
                ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
                ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
                ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
            ),
        )


def test_explicit_zero_rate_is_allowed_with_source() -> None:
    rate_set = IndiaChargeRateSet(
        stt_rate=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0"),
        ipft_rate=Decimal("0"),
        sebi_turnover_rate=Decimal("0"),
        gst_rate=Decimal("0"),
        component_sources=tuple(
            (component, "source", "v1")
            for component in (
                "stt",
                "stamp_duty",
                "exchange_txn",
                "ipft",
                "sebi_turnover_fee",
                "gst",
            )
        ),
        component_bases=tuple(
            (
                component,
                (
                    IndiaChargeBasis.CLIENT_TAXABLE_VALUE
                    if component == "gst"
                    else IndiaChargeBasis.TRANSACTION_VALUE
                ),
            )
            for component in (
                "stt",
                "stamp_duty",
                "exchange_txn",
                "ipft",
                "sebi_turnover_fee",
                "gst",
            )
        ),
    )

    assert rate_set.stt_rate == Decimal("0")


def test_caller_mapping_cannot_mutate_schedule_entry() -> None:
    rates_map = {
        (
            IndiaChargeProduct.EQUITY_DELIVERY,
            IndiaTradeSide.BUY,
            IndiaChargeEvent.TRADE,
        ): _rates()
    }
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="entry",
        rates=rates_map,
    )
    rates_map[
        (
            IndiaChargeProduct.EQUITY_DELIVERY,
            IndiaTradeSide.BUY,
            IndiaChargeEvent.TRADE,
        )
    ] = _rates()

    assert len(entry.rates) == 1


def test_naive_effective_at_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        IndiaChargeCalculationContext(
            transaction_value=Decimal("10"),
            currency="INR",
            exchange=IndianExchange.NSE,
            trade_side=IndiaTradeSide.BUY,
            product=IndiaChargeProduct.EQUITY_DELIVERY,
            effective_at=datetime(2026, 1, 1),
            brokerage=Decimal("0"),
            dp_charges=Decimal("0"),
            other_taxable_service_charges=Decimal("0"),
            stt_gst_treatment=IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
            stamp_duty_gst_treatment=IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
            pass_through_policy=_policy(),
            gst_policy_version="v",
            gst_policy_source_ref="s",
        )


def test_unsupported_exchange_rejected() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable):
        _context(exchange=IndianExchange.BSE)


def test_unsupported_product_rejected() -> None:
    # Product enum only supports four products; unsupported scope is represented
    # by a non-NSE exchange in this slice.
    with pytest.raises(IndiaChargeRuleUnavailable):
        _context(exchange=IndianExchange.BSE)


def test_option_exercise_intrinsic_values() -> None:
    call_context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        trade_side=IndiaTradeSide.BUY,
        transaction_value=Decimal("0"),
        premium_value=Decimal("100"),
        option_type=IndiaOptionType.CALL,
        quantity=Decimal("2"),
        settlement_price=Decimal("110"),
        strike=Decimal("100"),
        exercise_notional_value=Decimal("500"),
        brokerage=Decimal("0"),
        dp_charges=Decimal("0"),
        other_taxable_service_charges=Decimal("0"),
    )
    put_context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        trade_side=IndiaTradeSide.BUY,
        transaction_value=Decimal("0"),
        premium_value=Decimal("100"),
        option_type=IndiaOptionType.PUT,
        quantity=Decimal("2"),
        settlement_price=Decimal("90"),
        strike=Decimal("100"),
        exercise_notional_value=Decimal("500"),
        brokerage=Decimal("0"),
        dp_charges=Decimal("0"),
        other_taxable_service_charges=Decimal("0"),
    )

    assert call_context is not None
    assert put_context is not None


def test_option_intrinsic_value_never_negative() -> None:
    context = _context(
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        trade_side=IndiaTradeSide.BUY,
        transaction_value=Decimal("0"),
        premium_value=Decimal("100"),
        option_type=IndiaOptionType.CALL,
        quantity=Decimal("2"),
        settlement_price=Decimal("90"),
        strike=Decimal("100"),
        exercise_notional_value=Decimal("500"),
        brokerage=Decimal("0"),
        dp_charges=Decimal("0"),
        other_taxable_service_charges=Decimal("0"),
    )

    assert context is not None


def test_broker_absorbed_component_not_in_client_total() -> None:
    policy = IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.BROKER_ABSORBED,
        stamp_duty=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="policy-v1",
        source_ref="policy-source",
    )
    context = _context(pass_through_policy=policy)
    model = IndiaMarketChargeModel(schedule=_schedule())
    breakdown = model.calculate(context)

    stt = next(component for component in breakdown.components if component.name == "stt")
    assert stt.amount == Decimal("0")


def test_missing_pass_through_policy_fails_closed() -> None:
    with pytest.raises(IndiaChargeInputUnavailable):
        _context(pass_through_policy=None)


def test_missing_gst_taxable_input_fails_closed() -> None:
    with pytest.raises(IndiaChargeInputUnavailable):
        _context(brokerage=None)


def test_total_equals_sum_of_components() -> None:
    breakdown = IndiaMarketChargeModel(schedule=_schedule()).calculate(_context())

    assert breakdown.total == sum(
        (component.amount for component in breakdown.components), Decimal("0")
    )


def _exercise_policy() -> IndiaChargePassThroughPolicy:
    return IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        stamp_duty=IndiaChargeIncidence.NOT_APPLICABLE,
        exchange_txn=IndiaChargeIncidence.NOT_APPLICABLE,
        ipft=IndiaChargeIncidence.NOT_APPLICABLE,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="synthetic-exercise-policy-v1",
        source_ref="synthetic://exercise-policy",
    )


def _exercise_rates(
    *,
    exchange_basis: IndiaChargeBasis = IndiaChargeBasis.NOT_APPLICABLE,
) -> IndiaChargeRateSet:
    return IndiaChargeRateSet(
        stt_rate=Decimal("0.10"),
        stamp_duty_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0"),
        ipft_rate=Decimal("0"),
        sebi_turnover_rate=Decimal("0.01"),
        gst_rate=Decimal("0.18"),
        component_sources=tuple(
            (component, f"synthetic://{component}", "exercise-synthetic-v1")
            for component in (
                "stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee", "gst"
            )
        ),
        component_bases=(
            ("stt", IndiaChargeBasis.OPTION_INTRINSIC_VALUE),
            ("stamp_duty", IndiaChargeBasis.NOT_APPLICABLE),
            ("exchange_txn", exchange_basis),
            ("ipft", IndiaChargeBasis.NOT_APPLICABLE),
            ("sebi_turnover_fee", IndiaChargeBasis.OPTION_EXERCISE_NOTIONAL),
            ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
        ),
    )


def _exercise_model(
    *, exchange_basis: IndiaChargeBasis = IndiaChargeBasis.NOT_APPLICABLE
) -> IndiaMarketChargeModel:
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="synthetic-exercise-schedule-v1",
        rates={
            (
                IndiaChargeProduct.EQUITY_OPTIONS,
                IndiaTradeSide.BUY,
                IndiaChargeEvent.OPTION_EXERCISE,
            ): _exercise_rates(exchange_basis=exchange_basis)
        },
    )
    return IndiaMarketChargeModel(schedule=IndiaChargeSchedule((entry,)))


def _exercise_context(
    option_type: IndiaOptionType,
    *,
    settlement_price: Decimal,
    strike: Decimal,
) -> IndiaChargeCalculationContext:
    return _context(
        transaction_value=Decimal("7777"),
        product=IndiaChargeProduct.EQUITY_OPTIONS,
        trade_side=IndiaTradeSide.BUY,
        event=IndiaChargeEvent.OPTION_EXERCISE,
        premium_value=Decimal("999"),
        option_type=option_type,
        quantity=Decimal("2"),
        settlement_price=settlement_price,
        strike=strike,
        exercise_notional_value=Decimal("500"),
        brokerage=Decimal("1"),
        dp_charges=Decimal("0"),
        other_taxable_service_charges=Decimal("0"),
        stt_gst_treatment=IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
        stamp_duty_gst_treatment=IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
        pass_through_policy=_exercise_policy(),
    )


def _component_amount(breakdown, name: str) -> Decimal:
    return next(component.amount for component in breakdown.components if component.name == name)


def test_call_exercise_calculates_intrinsic_stt_and_separate_sebi_notional() -> None:
    result = _exercise_model().calculate(
        _exercise_context(
            IndiaOptionType.CALL,
            settlement_price=Decimal("110"),
            strike=Decimal("100"),
        )
    )

    assert _component_amount(result, "stt") == Decimal("2.00")
    assert _component_amount(result, "sebi_turnover_fee") == Decimal("5.00")
    assert _component_amount(result, "gst") == Decimal("1.08")
    assert result.total == Decimal("9.08")


def test_put_exercise_calculates_intrinsic_stt_and_separate_sebi_notional() -> None:
    result = _exercise_model().calculate(
        _exercise_context(
            IndiaOptionType.PUT,
            settlement_price=Decimal("90"),
            strike=Decimal("100"),
        )
    )

    assert _component_amount(result, "stt") == Decimal("2.00")
    assert _component_amount(result, "sebi_turnover_fee") == Decimal("5.00")
    assert _component_amount(result, "gst") == Decimal("1.08")
    assert result.total == Decimal("9.08")


@pytest.mark.parametrize(
    ("option_type", "settlement", "strike"),
    [
        (IndiaOptionType.CALL, Decimal("90"), Decimal("100")),
        (IndiaOptionType.PUT, Decimal("110"), Decimal("100")),
    ],
)
def test_out_of_the_money_exercise_has_zero_intrinsic_stt(
    option_type: IndiaOptionType, settlement: Decimal, strike: Decimal
) -> None:
    result = _exercise_model().calculate(
        _exercise_context(option_type, settlement_price=settlement, strike=strike)
    )

    assert _component_amount(result, "stt") == Decimal("0.00")
    assert _component_amount(result, "sebi_turnover_fee") == Decimal("5.00")


def test_exercise_rejects_unsupported_component_basis() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="unsupported charge basis"):
        _exercise_model(exchange_basis=IndiaChargeBasis.TRANSACTION_VALUE).calculate(
            _exercise_context(
                IndiaOptionType.CALL,
                settlement_price=Decimal("110"),
                strike=Decimal("100"),
            )
        )


def test_option_exercise_rejected_for_non_option_product() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="requires EQUITY_OPTIONS"):
        _context(
            product=IndiaChargeProduct.EQUITY_FUTURES,
            event=IndiaChargeEvent.OPTION_EXERCISE,
        )


def test_option_assignment_is_explicitly_unsupported() -> None:
    with pytest.raises(IndiaChargeRuleUnavailable, match="OPTION_ASSIGNMENT is unsupported"):
        _context(event="OPTION_ASSIGNMENT")


def test_not_applicable_incidence_with_positive_rate_fails_closed() -> None:
    policy = IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        stamp_duty=IndiaChargeIncidence.NOT_APPLICABLE,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="synthetic-not-applicable-v1",
        source_ref="synthetic://not-applicable",
    )
    with pytest.raises(IndiaChargeRuleUnavailable, match="NOT_APPLICABLE"):
        IndiaMarketChargeModel(schedule=_schedule()).calculate(
            _context(pass_through_policy=policy)
        )


def test_not_applicable_sourced_zero_rule_calculates_zero() -> None:
    rates = IndiaChargeRateSet(
        stt_rate=Decimal("0.001"),
        stamp_duty_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0.0000297"),
        ipft_rate=Decimal("0.000001"),
        sebi_turnover_rate=Decimal("0.000001"),
        gst_rate=Decimal("0.18"),
        component_sources=tuple(
            (component, f"synthetic://{component}", "zero-rule-v1")
            for component in (
                "stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee", "gst"
            )
        ),
        component_bases=(
            ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
            ("stamp_duty", IndiaChargeBasis.NOT_APPLICABLE),
            ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
            ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
            ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
            ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
        ),
    )
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="synthetic-zero-schedule-v1",
        rates={
            (IndiaChargeProduct.EQUITY_DELIVERY, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE): rates
        },
    )
    policy = IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        stamp_duty=IndiaChargeIncidence.NOT_APPLICABLE,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="synthetic-zero-policy-v1",
        source_ref="synthetic://zero-policy",
    )

    result = IndiaMarketChargeModel(schedule=IndiaChargeSchedule((entry,))).calculate(
        _context(pass_through_policy=policy)
    )

    assert _component_amount(result, "stamp_duty") == Decimal("0.00")
    assert any("stamp_duty:basis=NOT_APPLICABLE" in item for item in result.provenance)


def test_gst_uses_complete_client_taxable_base_and_explicit_treatments() -> None:
    include_stt = IndiaMarketChargeModel(schedule=_schedule()).calculate(_context())
    exclude_stt_include_stamp = IndiaMarketChargeModel(schedule=_schedule()).calculate(
        _context(
            stt_gst_treatment=IndiaRecoveryTaxTreatment.EXCLUDE_AS_QUALIFIED_PURE_AGENT,
            stamp_duty_gst_treatment=IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE,
        )
    )

    assert _component_amount(include_stt, "stt") == Decimal("10.00")
    assert _component_amount(include_stt, "stamp_duty") == Decimal("1.50")
    assert _component_amount(include_stt, "exchange_txn") == Decimal("0.30")
    assert _component_amount(include_stt, "ipft") == Decimal("0.01")
    assert _component_amount(include_stt, "sebi_turnover_fee") == Decimal("0.01")
    assert _component_amount(include_stt, "gst") == Decimal("4.02")
    assert include_stt.total == Decimal("27.84")

    assert _component_amount(exclude_stt_include_stamp, "gst") == Decimal("2.49")
    assert exclude_stt_include_stamp.total == Decimal("26.31")


def test_broker_absorbed_component_is_excluded_from_client_cost_and_gst_base() -> None:
    policy = IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.BROKER_ABSORBED,
        stamp_duty=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="synthetic-absorbed-policy-v1",
        source_ref="synthetic://absorbed",
    )

    result = IndiaMarketChargeModel(schedule=_schedule()).calculate(
        _context(pass_through_policy=policy)
    )

    assert _component_amount(result, "stt") == Decimal("0")
    assert _component_amount(result, "gst") == Decimal("2.22")
    assert result.total == Decimal("16.04")


def test_client_passthrough_component_is_included_in_cost_and_gst_base() -> None:
    result = IndiaMarketChargeModel(schedule=_schedule()).calculate(_context())

    assert _component_amount(result, "stt") == Decimal("10.00")
    assert _component_amount(result, "gst") == Decimal("4.02")


def test_component_rounding_is_half_up_per_component_before_total() -> None:
    rates = IndiaChargeRateSet(
        stt_rate=Decimal("0.005"),
        stamp_duty_rate=Decimal("0"),
        exchange_txn_rate=Decimal("0.005"),
        ipft_rate=Decimal("0"),
        sebi_turnover_rate=Decimal("0"),
        gst_rate=Decimal("0"),
        component_sources=tuple(
            (component, f"synthetic://{component}", "rounding-v1")
            for component in (
                "stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee", "gst"
            )
        ),
        component_bases=(
            ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
            ("stamp_duty", IndiaChargeBasis.TRANSACTION_VALUE),
            ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
            ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
            ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
            ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
        ),
    )
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="synthetic-rounding-v1",
        rates={
            (IndiaChargeProduct.EQUITY_DELIVERY, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE): rates
        },
    )
    result = IndiaMarketChargeModel(schedule=IndiaChargeSchedule((entry,))).calculate(
        _context(
            transaction_value=Decimal("1"),
            brokerage=Decimal("0"),
            dp_charges=Decimal("0"),
            other_taxable_service_charges=Decimal("0"),
        )
    )

    assert _component_amount(result, "stt") == Decimal("0.01")
    assert _component_amount(result, "exchange_txn") == Decimal("0.01")
    assert result.total == Decimal("0.02")


def test_provenance_records_basis_sources_and_policy_versions() -> None:
    result = IndiaMarketChargeModel(schedule=_schedule()).calculate(_context())

    assert "schedule_version=schedule-v1" in result.provenance
    assert any(item.startswith("schedule_interval=") for item in result.provenance)
    components = (
        "stt",
        "stamp_duty",
        "exchange_txn",
        "ipft",
        "sebi_turnover_fee",
        "gst",
    )
    for component in components:
        assert any(f"{component}:basis=" in item for item in result.provenance)
        assert any(
            f"{component}:source=" in item and "rule_version=" in item
            for item in result.provenance
        )
    assert "pass_through_policy=policy-v1" in result.provenance
    assert "pass_through_source=policy-source" in result.provenance
    assert "gst_policy=gst-policy-v1" in result.provenance
    assert "gst_policy_source=gst-policy-source" in result.provenance


def test_missing_gst_treatment_fails_before_breakdown() -> None:
    with pytest.raises(IndiaChargeInputUnavailable, match="stt_gst_treatment"):
        _context(stt_gst_treatment=None)


def test_public_basis_type_is_exported() -> None:
    assert "IndiaChargeBasis" in india_charges.__all__
    assert india_charges.IndiaChargeBasis is IndiaChargeBasis


def test_not_applicable_basis_requires_not_applicable_incidence() -> None:
    rates = _rates()
    rates_with_not_applicable_basis = IndiaChargeRateSet(
        stt_rate=rates.stt_rate,
        stamp_duty_rate=rates.stamp_duty_rate,
        exchange_txn_rate=rates.exchange_txn_rate,
        ipft_rate=rates.ipft_rate,
        sebi_turnover_rate=rates.sebi_turnover_rate,
        gst_rate=rates.gst_rate,
        component_sources=rates.component_sources,
        component_bases=(
            ("stt", IndiaChargeBasis.TRANSACTION_VALUE),
            ("stamp_duty", IndiaChargeBasis.NOT_APPLICABLE),
            ("exchange_txn", IndiaChargeBasis.TRANSACTION_VALUE),
            ("ipft", IndiaChargeBasis.TRANSACTION_VALUE),
            ("sebi_turnover_fee", IndiaChargeBasis.TRANSACTION_VALUE),
            ("gst", IndiaChargeBasis.CLIENT_TAXABLE_VALUE),
        ),
    )
    entry = IndiaChargeScheduleEntry(
        effective_from=datetime(2026, 1, 1, tzinfo=IST),
        effective_to=None,
        version="synthetic-inconsistent-basis-v1",
        rates={
            (IndiaChargeProduct.EQUITY_DELIVERY, IndiaTradeSide.BUY, IndiaChargeEvent.TRADE):
            rates_with_not_applicable_basis
        },
    )

    with pytest.raises(IndiaChargeRuleUnavailable, match="NOT_APPLICABLE"):
        IndiaMarketChargeModel(schedule=IndiaChargeSchedule((entry,))).calculate(_context())


def test_broker_absorbed_incidence_remains_in_provenance() -> None:
    policy = IndiaChargePassThroughPolicy(
        stt=IndiaChargeIncidence.BROKER_ABSORBED,
        stamp_duty=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        exchange_txn=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        ipft=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        sebi_turnover_fee=IndiaChargeIncidence.CLIENT_PASSTHROUGH,
        version="synthetic-absorbed-policy-v1",
        source_ref="synthetic://absorbed",
    )

    result = IndiaMarketChargeModel(schedule=_schedule()).calculate(
        _context(pass_through_policy=policy)
    )

    assert _component_amount(result, "stt") == Decimal("0")
    assert any(
        "stt:basis=TRANSACTION_VALUE:" in item and "incidence=BROKER_ABSORBED" in item
        for item in result.provenance
    )
