from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quantx.domain.value_objects import InstrumentId
from quantx.markets.india.physical_settlement_charges import (
    IndiaPhysicalSettlementCollectionDisposition,
    IndiaPhysicalSettlementContractInput,
    IndiaPhysicalSettlementInputUnavailable,
    IndiaPhysicalSettlementJurisdictionSource,
    IndiaPhysicalSettlementStampDutyClientContext,
    IndiaPhysicalSettlementStampDutyModel,
    IndiaPhysicalSettlementStampDutyRates,
    IndiaPhysicalSettlementStampDutySchedule,
    IndiaPhysicalSettlementStampDutyScheduleEntry,
    IndiaPhysicalSettlementRuleUnavailable,
)

D = Decimal
IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 1, 1, tzinfo=IST)
SPLIT = datetime(2026, 12, 7, tzinfo=IST)


def _rates(
    *,
    delivery: Decimal | None = D("0.00015"),
    non_delivery: Decimal | None = D("0.00003"),
) -> IndiaPhysicalSettlementStampDutyRates:
    return IndiaPhysicalSettlementStampDutyRates(
        delivery_stamp_duty_rate=delivery,
        non_delivery_stamp_duty_rate=non_delivery,
        component_sources=(
            (
                "delivery_stamp_duty",
                "synthetic://india-physical-stamp/delivery",
                "synthetic-v1",
            ),
            (
                "non_delivery_stamp_duty",
                "synthetic://india-physical-stamp/non-delivery",
                "synthetic-v1",
            ),
        ),
    )


def _entry(
    *,
    rates: IndiaPhysicalSettlementStampDutyRates | None = None,
    effective_from: datetime = START,
    effective_to: datetime | None = None,
    version: str = "synthetic-physical-stamp-v1",
) -> IndiaPhysicalSettlementStampDutyScheduleEntry:
    return IndiaPhysicalSettlementStampDutyScheduleEntry(
        effective_from=effective_from,
        effective_to=effective_to,
        version=version,
        rates=rates or _rates(),
    )


def _contract(
    settlement_id: str = "NCL-DELIVERY-001",
    *,
    buy: Decimal = D("100"),
    sell: Decimal = D("40"),
    price: Decimal = D("500"),
) -> IndiaPhysicalSettlementContractInput:
    return IndiaPhysicalSettlementContractInput(
        settlement_id=settlement_id,
        security_id=InstrumentId("NSE", "RELIANCE"),
        buy_quantity=buy,
        sell_quantity=sell,
        final_settlement_price=price,
        final_settlement_price_source_ref="synthetic://ncl/final-settlement-price",
        final_settlement_price_method_version="synthetic-price-v1",
        obligation_source_ref="synthetic://ncl/clearing-obligations",
    )


def _context(
    *settlements: IndiaPhysicalSettlementContractInput,
    **overrides: object,
) -> IndiaPhysicalSettlementStampDutyClientContext:
    values: dict[str, object] = {
        "settlement_date": datetime(2026, 11, 30, tzinfo=IST),
        "client_code": "CLIENT-001",
        "is_proprietary": False,
        "trading_member_code": "TM-001",
        "client_code_source_ref": "synthetic://clearing/client-code",
        "client_state_ut": "MAHARASHTRA",
        "client_state_source_ref": "synthetic://kyc/client-state",
        "trading_member_state_ut": "MAHARASHTRA",
        "trading_member_state_source_ref": "synthetic://member/state",
        "settlements": settlements or (_contract(),),
    }
    values.update(overrides)
    return IndiaPhysicalSettlementStampDutyClientContext(**values)  # type: ignore[arg-type]


def _model(*entries: IndiaPhysicalSettlementStampDutyScheduleEntry) -> IndiaPhysicalSettlementStampDutyModel:
    schedule_entries = entries or (_entry(),)
    return IndiaPhysicalSettlementStampDutyModel(
        IndiaPhysicalSettlementStampDutySchedule(schedule_entries)
    )


def test_physical_stamp_duty_computes_delivery_and_non_delivery_components() -> None:
    result = _model().calculate(_context())

    assert result.collection_disposition is (
        IndiaPhysicalSettlementCollectionDisposition.COLLECTED_BY_NCL
    )
    assert result.jurisdiction_state_ut == "MAHARASHTRA"
    assert result.jurisdiction_source is IndiaPhysicalSettlementJurisdictionSource.CLIENT_CODE
    assert result.settlements[0].buy_deliverable_quantity == D("60")
    assert result.settlements[0].buy_non_deliverable_quantity == D("40")
    assert result.settlements[0].buy_deliverable_value == D("30000")
    assert result.settlements[0].buy_non_deliverable_value == D("20000")
    assert result.settlements[0].delivery_stamp_duty == D("4.50")
    assert result.settlements[0].non_delivery_stamp_duty == D("0.60")
    assert result.settlements[0].total == D("5.10")
    assert result.client_level_total == D("5")
    assert "schedule:synthetic-physical-stamp-v1" in result.provenance
    assert any("obligation_source:" in item for item in result.provenance)
    assert any("final_settlement_price_method:" in item for item in result.provenance)


def test_physical_stamp_duty_handles_non_delivery_only() -> None:
    result = _model().calculate(
        _context(_contract(buy=D("40"), sell=D("100")))
    )

    line = result.settlements[0]
    assert line.buy_deliverable_quantity == D("0")
    assert line.buy_non_deliverable_quantity == D("40")
    assert line.delivery_stamp_duty == D("0.00")
    assert line.non_delivery_stamp_duty == D("0.60")
    assert result.client_level_total == D("1")


def test_physical_stamp_duty_handles_equal_receivable_and_deliverable_quantities() -> None:
    result = _model().calculate(
        _context(_contract(buy=D("100"), sell=D("100")))
    )

    line = result.settlements[0]
    assert line.buy_deliverable_quantity == D("0")
    assert line.buy_non_deliverable_quantity == D("100")
    assert line.delivery_stamp_duty == D("0.00")
    assert line.non_delivery_stamp_duty == D("1.50")
    assert result.client_level_total == D("2")


def test_client_rounding_occurs_after_summing_each_contract_delivery_settlement() -> None:
    first = _contract("NCL-DELIVERY-001", buy=D("1"), sell=D("0"), price=D("166.67"))
    second = _contract("NCL-DELIVERY-002", buy=D("1"), sell=D("0"), price=D("166.67"))

    result = _model().calculate(_context(first, second))

    assert tuple(line.delivery_stamp_duty for line in result.settlements) == (
        D("0.25"),
        D("0.25"),
    )
    assert result.client_level_total == D("1")


def test_component_rounding_is_half_up_to_paise_before_client_rounding() -> None:
    settlement = _contract(buy=D("1"), sell=D("0"), price=D("333.33"))
    model = _model(_entry(rates=_rates(non_delivery=D("0"))))

    result = model.calculate(_context(settlement))

    assert result.settlements[0].delivery_stamp_duty == D("0.50")
    assert result.client_level_total == D("1")


def test_sikkim_is_not_collected_by_ncl_and_is_not_a_zero_rate() -> None:
    result = _model().calculate(
        _context(
            client_state_ut="SIKKIM",
            client_state_source_ref="synthetic://kyc/client-state-sikkim",
        )
    )

    assert result.collection_disposition is (
        IndiaPhysicalSettlementCollectionDisposition.NOT_COLLECTED_BY_NCL
    )
    assert result.client_level_total is None
    assert result.schedule_version is None
    assert result.settlements == ()
    assert "collection_disposition:NOT_COLLECTED_BY_NCL_FOR_SIKKIM" in result.provenance


def test_trading_member_state_is_used_only_when_client_state_is_unavailable() -> None:
    result = _model().calculate(
        _context(
            client_state_ut=None,
            client_state_source_ref=None,
            trading_member_state_ut="KARNATAKA",
        )
    )

    assert result.jurisdiction_state_ut == "KARNATAKA"
    assert result.jurisdiction_source is (
        IndiaPhysicalSettlementJurisdictionSource.TRADING_MEMBER_FALLBACK
    )
    assert any("trading_member_state_fallback:" in item for item in result.provenance)


def test_missing_client_and_member_state_fails_closed() -> None:
    with pytest.raises(
        IndiaPhysicalSettlementInputUnavailable,
        match="client State/UT and trading-member fallback State/UT",
    ):
        _context(
            client_state_ut=None,
            client_state_source_ref=None,
            trading_member_state_ut=None,
            trading_member_state_source_ref=None,
        )


def test_proprietary_transaction_uses_member_code_as_client_code() -> None:
    context = _context(
        client_code="TM-001",
        is_proprietary=True,
    )
    result = _model().calculate(context)

    assert result.collection_disposition is (
        IndiaPhysicalSettlementCollectionDisposition.COLLECTED_BY_NCL
    )
    assert "client_code_kind:TRADING_MEMBER_CODE" in result.provenance
    assert "TM-001" not in "|".join(result.provenance)


def test_proprietary_client_code_cannot_differ_from_member_code() -> None:
    with pytest.raises(
        IndiaPhysicalSettlementInputUnavailable,
        match="proprietary settlement must use the trading-member code",
    ):
        _context(is_proprietary=True)


def test_missing_component_rate_is_not_converted_to_zero() -> None:
    model = _model(_entry(rates=_rates(delivery=None)))

    with pytest.raises(
        IndiaPhysicalSettlementRuleUnavailable,
        match="delivery stamp-duty rate is unavailable",
    ):
        model.calculate(_context())


def test_rates_require_source_evidence_for_both_components() -> None:
    with pytest.raises(ValueError, match="every physical stamp component"):
        IndiaPhysicalSettlementStampDutyRates(
            delivery_stamp_duty_rate=D("0.00015"),
            non_delivery_stamp_duty_rate=D("0.00003"),
            component_sources=(
                (
                    "delivery_stamp_duty",
                    "synthetic://india-physical-stamp/delivery",
                    "synthetic-v1",
                ),
            ),
        )


def test_settlement_requires_price_and_obligation_provenance() -> None:
    with pytest.raises(ValueError, match="final_settlement_price_source_ref"):
        IndiaPhysicalSettlementContractInput(
            settlement_id="NCL-DELIVERY-001",
            security_id=InstrumentId("NSE", "RELIANCE"),
            buy_quantity=D("100"),
            sell_quantity=D("40"),
            final_settlement_price=D("500"),
            final_settlement_price_source_ref="",
            final_settlement_price_method_version="synthetic-price-v1",
            obligation_source_ref="synthetic://ncl/obligations",
        )
    with pytest.raises(ValueError, match="obligation_source_ref"):
        IndiaPhysicalSettlementContractInput(
            settlement_id="NCL-DELIVERY-001",
            security_id=InstrumentId("NSE", "RELIANCE"),
            buy_quantity=D("100"),
            sell_quantity=D("40"),
            final_settlement_price=D("500"),
            final_settlement_price_source_ref="synthetic://ncl/price",
            final_settlement_price_method_version="synthetic-price-v1",
            obligation_source_ref="",
        )


def test_duplicate_settlement_ids_are_rejected() -> None:
    settlement = _contract()
    with pytest.raises(ValueError, match="settlement_id values must be unique"):
        _context(settlement, settlement)


def test_empty_settlement_group_is_rejected() -> None:
    with pytest.raises(
        IndiaPhysicalSettlementInputUnavailable,
        match="settlements must be a non-empty",
    ):
        _context(settlements=())


def test_missing_effective_schedule_coverage_fails_closed() -> None:
    model = _model(
        _entry(effective_from=START, effective_to=SPLIT)
    )
    with pytest.raises(
        IndiaPhysicalSettlementRuleUnavailable,
        match="no physical stamp schedule covers",
    ):
        model.calculate(
            _context(settlement_date=datetime(2027, 1, 1, tzinfo=IST))
        )


def test_overlapping_schedule_intervals_are_rejected() -> None:
    first = _entry(effective_from=START, effective_to=SPLIT)
    second = _entry(effective_from=datetime(2026, 12, 1, tzinfo=IST))
    with pytest.raises(ValueError, match="must not overlap"):
        IndiaPhysicalSettlementStampDutySchedule((first, second))


def test_schedule_boundaries_must_be_ist_midnight_instants() -> None:
    with pytest.raises(ValueError, match="Asia/Kolkata midnight"):
        _entry(effective_from=datetime(2026, 1, 1, 9, 15, tzinfo=IST))


@pytest.mark.parametrize(
    "invalid",
    [D("NaN"), D("Infinity"), D("-0.01")],
)
def test_contract_decimal_inputs_reject_non_finite_or_negative_values(
    invalid: Decimal,
) -> None:
    with pytest.raises(ValueError):
        _contract(buy=invalid)


def test_contract_decimal_inputs_reject_non_decimal_values() -> None:
    with pytest.raises(TypeError, match="buy_quantity must be a Decimal"):
        _contract(buy=100)  # type: ignore[arg-type]


def test_client_settlement_date_must_be_aware() -> None:
    with pytest.raises(
        IndiaPhysicalSettlementInputUnavailable, match="settlement_date must be timezone-aware"
    ):
        _context(settlement_date=datetime(2026, 11, 30))


def test_client_code_source_is_required() -> None:
    with pytest.raises(ValueError, match="client_code_source_ref"):
        _context(client_code_source_ref="")


def test_client_state_source_is_required_when_state_is_known() -> None:
    with pytest.raises(ValueError, match="client_state_source_ref"):
        _context(client_state_source_ref=None)


def test_state_source_cannot_be_claimed_without_state() -> None:
    with pytest.raises(ValueError, match="requires client_state_ut"):
        _context(client_state_ut=None, client_state_source_ref="synthetic://orphan-state")


def test_result_does_not_expose_raw_client_code() -> None:
    result = _model().calculate(_context())
    assert "CLIENT-001" not in "|".join(result.provenance)
