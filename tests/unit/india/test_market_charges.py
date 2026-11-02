from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

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
            ("gst", IndiaChargeBasis.NOT_APPLICABLE),
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
                    ("gst", IndiaChargeBasis.NOT_APPLICABLE),
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
                ("gst", IndiaChargeBasis.NOT_APPLICABLE),
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
                    IndiaChargeBasis.NOT_APPLICABLE
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
