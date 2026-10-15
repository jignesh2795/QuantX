"""Public-surface contracts for the India market-pack adapters.

Covers the value-level guarantees the India pack owes the neutral contract:
approved rule-code messages are rendered from per-code trusted templates,
and evidence metadata, rule names, and rule reasons are projected onto
approved values before they can reach a user or the serialized record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.india.domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
)
from quantx.india.execution_rules import (
    IndiaExecutionRuleEngine,
    IndiaRuleCheck,
    IndiaRuleDecision,
    IndiaRuleResult,
)
from quantx.india.market_checks import (
    IndiaCompatCheck,
    IndiaSessionCheck,
    approved_provenance,
    approved_rule_set_version,
    sanitize_rule_reason,
    sanitize_session_rejection,
)
from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult
from quantx.ports.market_checks import (
    RULE_CHECK_PASSED_REASON,
    RULE_CHECK_WITHHELD_REASON,
    MarketCheckOutcome,
    MarketCheckStage,
)


def _approved_request() -> ApprovedExecutionRequest:
    """A minimal approved request for the India region/equity market."""
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    instrument = Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _compat_evaluator(
    *,
    reason: str,
    checks: tuple[IndiaRuleCheck, ...] = (),
    version: str | None = "rules-v1",
    provenance: str | None = "test-venue",
):
    def run(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            reason,
            checks=checks,
            rule_set_version=version,
            provenance=provenance,
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return run


def _session_evaluator(reason: str):
    def run(request):
        return IndiaSessionResult(
            IndiaSessionDecision.BLOCK,
            reason,
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            calendar_evaluated=True,
        )

    return run


# ---------------------------------------------------------------------------
# Approved messages stay byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
        "INDIA_LOT_SIZE_INVALID: instrument lot size is invalid",
        "INDIA_QUANTITY_INVALID: quantity must be a positive number",
        "INDIA_PRICE_TICK_INVALID: limit_price does not align to tick size 0.05",
        "INDIA_DERIVATIVE_METADATA_INVALID: derivative contract metadata is not coherent",
        "INDIA_SEGMENT_INVALID: asset class EQUITY must not use segment FO",
        "INDIA_PRICE_BAND_INVALID: price 120 is outside [90, 110]",
        "INDIA_QUANTITY_FREEZE_INVALID: quantity 500 exceeds freeze 100",
        "INDIA_RULE_DATA_UNAVAILABLE: venue rule scope is unknown",
        "INDIA_SESSION_DATA_UNAVAILABLE: calendar coverage is unknown",
    ],
)
def test_approved_rule_messages_pass_through_unchanged(reason: str) -> None:
    assert sanitize_rule_reason(reason) == reason


def test_approved_aggregate_reason_is_preserved_byte_for_byte() -> None:
    aggregate = (
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25; "
        "INDIA_QUANTITY_FREEZE_INVALID: quantity 1 exceeds freeze 10000"
    )
    assert sanitize_rule_reason(aggregate) == aggregate


@pytest.mark.parametrize(
    "reason",
    [
        None,
        "",
        "   ",
        42,
        "INDIA_LOT_SIZE_INVALID",
        "INDIA_LOT_SIZE_INVALID:quantity 1 is not a multiple of lot size 25",
        "NOT_INDIA_CODE: everything is fine",
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25 "
        "and the desk approved an override",
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25; "
        "INDIA_QUANTITY_INVALID: not an approved message",
        "INDIA_LOT_SIZE_INVALID: quantity one is not a multiple of lot size 25",
        "INDIA_PRICE_TICK_INVALID: mid_price does not align to tick size 0.05",
        "Traceback (most recent call last): INDIA_LOT_SIZE_INVALID: lot size",
    ],
)
def test_unapproved_rule_reasons_are_withheld(reason: object) -> None:
    assert sanitize_rule_reason(reason) is None


def test_session_rejection_vocabulary() -> None:
    assert sanitize_session_rejection("india trading session is closed") == (
        "india trading session is closed"
    )
    assert sanitize_session_rejection("india trading calendar holiday") == (
        "india trading calendar holiday"
    )
    assert sanitize_session_rejection("  india trading session is closed  ") == (
        "india trading session is closed"
    )
    assert (
        sanitize_session_rejection(
            "INDIA_SESSION_SCOPE_MISMATCH: calendar exchange does not match request market"
        )
        == "INDIA_SESSION_SCOPE_MISMATCH: calendar exchange does not match request market"
    )
    assert sanitize_session_rejection("venue ops note XJ-42: session halted") is None


# ---------------------------------------------------------------------------
# Engine-produced messages stay inside the trusted templates
# ---------------------------------------------------------------------------


def _derivative_spec(**overrides):
    values: dict = {
        "instrument_id": InstrumentId("NSE", "NIFTY26JANFUT"),
        "symbol": "NIFTY26JANFUT",
        "asset_class": AssetClass.FUTURE,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.DERIVATIVES,
        "expiry": datetime(2026, 1, 29, tzinfo=UTC),
        "underlying": "NIFTY",
    }
    values.update(overrides)
    return IndianInstrumentSpec(**values)


def _order(**overrides):
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("2"),
    }
    values.update(overrides)
    return Order(**values)


def test_derivative_metadata_reason_carries_no_exception_text() -> None:
    """The derivative-metadata rejection names the incoherence, never the
    validation exception text it was raised from."""
    result = IndiaExecutionRuleEngine().validate(
        _derivative_spec(underlying=None),
        _order(instrument=InstrumentId("NSE", "NIFTY26JANFUT")),
    )

    assert result.decision is IndiaRuleDecision.REJECT
    assert result.reason == (
        "INDIA_DERIVATIVE_METADATA_INVALID: derivative contract metadata is not coherent"
    )
    assert sanitize_rule_reason(result.reason) == result.reason
    assert "underlying" not in result.reason


def test_price_tick_reason_carries_no_raw_price() -> None:
    """The price-tick rejection names the aligned field and the tick size,
    not the offending (possibly non-finite) price value."""
    result = IndiaExecutionRuleEngine().validate(
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "TCS"),
            symbol="TCS",
            asset_class=AssetClass.EQUITY,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
        ),
        _order(order_type=OrderType.LIMIT, limit_price=Decimal("112.34")),
    )

    assert result.decision is IndiaRuleDecision.REJECT
    assert result.reason == "INDIA_PRICE_TICK_INVALID: limit_price does not align to tick size 0.05"
    assert sanitize_rule_reason(result.reason) == result.reason
    assert "112.34" not in result.reason


def test_order_type_reason_uses_the_enum_value() -> None:
    """An unsupported order type is named by a bounded vocabulary token,
    never by a repr or an arbitrary value."""
    order = _order()
    object.__setattr__(order, "order_type", "WEIRD")
    result = IndiaExecutionRuleEngine().validate(
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "TCS"),
            symbol="TCS",
            asset_class=AssetClass.EQUITY,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
        ),
        order,
    )

    assert result.decision is IndiaRuleDecision.REJECT
    assert result.reason == "INDIA_ORDER_TYPE_INVALID: unsupported order type unknown"
    assert sanitize_rule_reason(result.reason) == result.reason
    assert "'WEIRD'" not in result.reason


def test_multi_violation_aggregate_from_the_real_engine_is_preserved() -> None:
    """A real multi-violation aggregate is approved segment by segment and
    reaches the public surface unchanged."""
    result = IndiaExecutionRuleEngine().validate(
        IndianInstrumentSpec(
            instrument_id=InstrumentId("NSE", "TCS"),
            symbol="TCS",
            asset_class=AssetClass.EQUITY,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            lot_size=Decimal("25"),
        ),
        _order(order_type=OrderType.LIMIT, limit_price=Decimal("112.34"), quantity=Decimal("1")),
    )

    assert result.decision is IndiaRuleDecision.REJECT
    assert result.reason.count("; ") == 1
    assert sanitize_rule_reason(result.reason) == result.reason


# ---------------------------------------------------------------------------
# Evidence metadata projection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["rules-v1", "NSE-EQ-2026-01", "band-1", "test-calendar-v1"])
def test_approved_rule_set_versions_preserved(version: str) -> None:
    assert approved_rule_set_version(version) == version


@pytest.mark.parametrize(
    "version",
    [
        None,
        "",
        "rules v1 (draft)",
        "internal desk note",
        "RULES-V1-" + "FINAL" * 20,
        'File "secret.py" leak',
        123,
    ],
)
def test_unapproved_rule_set_versions_dropped(version: object) -> None:
    assert approved_rule_set_version(version) is None


@pytest.mark.parametrize("provenance", ["test-venue", "test-calendar", "test-venue-rules"])
def test_approved_provenance_preserved(provenance: str) -> None:
    assert approved_provenance(provenance) == provenance


@pytest.mark.parametrize(
    "provenance",
    [
        None,
        "",
        "internal desk note for the NSE equity rule book",
        'File "secret.py" leak',
        1.5,
    ],
)
def test_unapproved_provenance_dropped(provenance: object) -> None:
    assert approved_provenance(provenance) is None


# ---------------------------------------------------------------------------
# Adapter projection
# ---------------------------------------------------------------------------


def test_unapproved_rule_name_collapses_to_fixed_identity() -> None:
    evaluator = _compat_evaluator(
        reason="INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
        checks=(
            IndiaRuleCheck(
                "quantity", False, "INDIA_QUANTITY_INVALID: quantity must be a positive number"
            ),
            IndiaRuleCheck("desk_internal_risk_rule", True, "internal desk threshold"),
            IndiaRuleCheck("tick", True, "tick size ok"),
        ),
    )
    evidence = IndiaCompatCheck(evaluator)(_approved_request()).evidence

    assert evidence is not None
    assert [check.name for check in evidence.rule_checks] == ["quantity", "india-rule", "tick"]
    assert [check.reason for check in evidence.rule_checks] == [
        "INDIA_QUANTITY_INVALID: quantity must be a positive number",
        RULE_CHECK_PASSED_REASON,
        RULE_CHECK_PASSED_REASON,
    ]


def test_failed_rule_reason_with_unapproved_suffix_is_withheld() -> None:
    evaluator = _compat_evaluator(
        reason="INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
        checks=(
            IndiaRuleCheck(
                "quantity",
                False,
                "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25 XJ-99",
            ),
        ),
    )
    evidence = IndiaCompatCheck(evaluator)(_approved_request()).evidence

    assert evidence is not None
    assert evidence.rule_checks[0].reason == RULE_CHECK_WITHHELD_REASON


def test_unapproved_metadata_never_reaches_adapter_evidence() -> None:
    evaluator = _compat_evaluator(
        reason="INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
        version="rules v1 (draft)",
        provenance="internal desk note for the NSE equity rule book",
    )
    evidence = IndiaCompatCheck(evaluator)(_approved_request()).evidence

    assert evidence is not None
    assert evidence.rule_set_version is None
    assert evidence.provenance is None


def test_approved_metadata_reaches_adapter_evidence() -> None:
    evaluator = _compat_evaluator(
        reason="INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
        version="rules-v1",
        provenance="test-venue",
    )
    evidence = IndiaCompatCheck(evaluator)(_approved_request()).evidence

    assert evidence is not None
    assert evidence.rule_set_version == "rules-v1"
    assert evidence.provenance == "test-venue"


def test_session_adapter_records_established_evidence() -> None:
    result = IndiaSessionCheck(_session_evaluator("india trading session is closed"))(
        _approved_request()
    )

    assert result.outcome is MarketCheckOutcome.BLOCK
    assert result.failure_code == "india.session-calendar.rejected"
    assert result.reason == (
        "india session/calendar blocked the request: india trading session is closed"
    )
    assert result.evidence is not None
    assert result.evidence.rule_set_version == "test-calendar-v1"
    assert result.evidence.provenance == "test-calendar"
    assert result.evidence.stage is MarketCheckStage.PRE_DISPATCH


def test_unapproved_session_reason_falls_back_to_static_template() -> None:
    result = IndiaSessionCheck(
        _session_evaluator("venue ops note XJ-42: session halted pending review")
    )(_approved_request())

    assert result.outcome is MarketCheckOutcome.BLOCK
    assert result.reason == "india session/calendar blocked the request"
    assert "XJ-42" not in result.reason
