"""Synthetic-only tests for the LIVE risk evidence contract and snapshot builder."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.application.live_risk_evidence import (
    ConcurrencyAdmission,
    LiveRiskEvidence,
    LiveRiskEvidenceError,
    LiveRiskPolicy,
    PendingScopeResult,
    PendingScopeStatus,
    build_live_risk_inputs,
    evaluate_live_risk_evidence,
    validate_live_risk_approval_binding,
)
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.risk import PreTradeRiskEngine, RiskDecision
from quantx.domain.risk_evidence import (
    EvidenceStatus,
    LivePositionEvidence,
    MarginEvidence,
    PositionSurface,
    PositionSurfaceEvidence,
    RealizedDailyPnlEvidence,
    RealizedPnlSource,
    ReferencePriceEvidence,
    WholeAccountPositionEvidence,
)
from quantx.domain.value_objects import (
    AccountId,
    BrokerConnectionId,
    Money,
    ProductCode,
)
from tests.unit.application.test_live_risk import (
    EVALUATED_AT,
    OBSERVED_AT,
    _instrument,
    _limits,
    _request,
)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
BASE_CURRENCY = "INR"
TRADING_DAY = date(2026, 1, 1)
DAY_START_AT = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)


def _financial() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.LIVE_BROKER,
        Money(Decimal("100000"), BASE_CURRENCY),
        Money(Decimal("100000"), BASE_CURRENCY),
        Money(Decimal("0"), BASE_CURRENCY),
        Money(Decimal("0"), BASE_CURRENCY),
        Money(Decimal("100000"), BASE_CURRENCY),
        Money(Decimal("100000"), BASE_CURRENCY),
    )


def _position(**overrides) -> LivePositionEvidence:
    values = {
        "instrument": _instrument(),
        "product": ProductCode("CNC"),
        "quantity": Decimal("10"),
        "average_price": Decimal("200"),
        "mark_price": Decimal("100"),
        "mark_observed_at": OBSERVED_AT,
        "mark_source": "synthetic-test-fixture",
        "currency": BASE_CURRENCY,
    }
    values.update(overrides)
    return LivePositionEvidence(**values)


def _positions(
    positions: tuple[LivePositionEvidence, ...] | None = None,
    *,
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
    surface_status: EvidenceStatus = EvidenceStatus.COMPLETE,
    observed_at: datetime = OBSERVED_AT,
) -> WholeAccountPositionEvidence:
    rows = positions if positions is not None else ()
    return WholeAccountPositionEvidence(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        surfaces=(
            PositionSurfaceEvidence(
                PositionSurface.POSITIONS, surface_status, observed_at,
                "synthetic-v1", "synthetic-test-fixture", len(rows),
            ),
            PositionSurfaceEvidence(
                PositionSurface.HOLDINGS, surface_status, observed_at,
                "synthetic-v1", "synthetic-test-fixture", 0,
            ),
            PositionSurfaceEvidence(
                PositionSurface.MARKS, surface_status, observed_at,
                "synthetic-v1", "synthetic-test-fixture", len(rows),
            ),
        ),
        positions=rows,
        completeness=status,
        merge_policy="synthetic-no-overlap-v1",
        observed_at=observed_at,
        version="synthetic-v1",
        provenance="synthetic-test-fixture",
    )


def _pnl(**overrides) -> RealizedDailyPnlEvidence:
    values = {
        "account_id": ACCOUNT,
        "connection_id": CONNECTION,
        "broker_id": "test-broker",
        "trading_day": TRADING_DAY,
        "day_start_at": datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        "as_of": OBSERVED_AT,
        "amount": Money(Decimal("2500"), BASE_CURRENCY),
        "charges_daily": Money(Decimal("0"), BASE_CURRENCY),
        "source": RealizedPnlSource.BROKER_REPORTED,
        "scope": "WHOLE_ACCOUNT",
        "completeness": EvidenceStatus.COMPLETE,
        "covered_surfaces": ("synthetic-test-fixture",),
        "uncaptured_activity": (),
        "version": "synthetic-v1",
        "provenance": "synthetic-test-fixture",
    }
    values.update(overrides)
    return RealizedDailyPnlEvidence(**values)


def _evidence(
    *,
    positions: WholeAccountPositionEvidence | None = None,
    pnl: RealizedDailyPnlEvidence | None = None,
    margin_available: Decimal = Decimal("100000"),
    margin_required: Decimal = Decimal("1000"),
    financial_completeness: EvidenceStatus = EvidenceStatus.COMPLETE,
    reference_price: ReferencePriceEvidence | None = None,
    assembled_at: datetime = EVALUATED_AT,
) -> LiveRiskEvidence:
    instrument = _instrument()
    if reference_price is None:
        reference_price = ReferencePriceEvidence(
            instrument=instrument,
            price=Decimal("100"),
            observed_at=OBSERVED_AT,
            source="synthetic-test-fixture",
            currency=BASE_CURRENCY,
        )
    return LiveRiskEvidence(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        broker_id="test-broker",
        base_currency=BASE_CURRENCY,
        completeness=EvidenceStatus.COMPLETE,
        financial_state=replace(
            _financial(),
            margin_available=Money(margin_available, BASE_CURRENCY),
        ),
        financial_state_observed_at=OBSERVED_AT,
        financial_state_completeness=financial_completeness,
        broker_constraints=(),
        positions=positions if positions is not None else _positions(),
        realized_daily_pnl=pnl if pnl is not None else _pnl(),
        margin=MarginEvidence(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            required_margin=Money(margin_required, BASE_CURRENCY),
            available_margin=Money(margin_available, BASE_CURRENCY),
            observed_at=OBSERVED_AT,
            source="synthetic-test-fixture",
            completeness=EvidenceStatus.COMPLETE,
            version="synthetic-v1",
            provenance="synthetic-test-fixture",
        ),
        reference_price=reference_price,
        assembled_at=assembled_at,
        evidence_id="synthetic-evidence-1",
        version="synthetic-v1",
        provenance="synthetic-test-fixture",
    )


def _policy():
    return LiveRiskPolicy(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        broker_id="test-broker",
        base_currency=BASE_CURRENCY,
        limits=_limits(max_drawdown=None, max_instrument_concentration=None),
    )


def _build(evidence: LiveRiskEvidence | None = None, *, request=None):
    return build_live_risk_inputs(
        request or replace(_request(), required_margin=Decimal("1000")),
        policy=_policy(),
        evidence=evidence if evidence is not None else _evidence(),
        trading_day=TRADING_DAY,
        trading_day_start_at=DAY_START_AT,
        evaluated_at=EVALUATED_AT,
    )


def test_pending_scope_result_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        PendingScopeResult(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            status=PendingScopeStatus.CLEAR,
            reason="synthetic clear result",
            checked_at=datetime(2026, 1, 1, 9, 30),
        )


def test_pending_scope_result_accepts_aware_timestamp():
    result = PendingScopeResult(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        status=PendingScopeStatus.CLEAR,
        reason="synthetic clear result",
        checked_at=EVALUATED_AT,
    )
    assert result.checked_at == EVALUATED_AT


def test_concurrency_admission_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        ConcurrencyAdmission(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            request_fingerprint="synthetic-fingerprint",
            admission_id="synthetic-admission",
            acquired_at=datetime(2026, 1, 1, 9, 30),
            expires_at=EVALUATED_AT + timedelta(seconds=30),
        )


def test_builder_rejects_order_without_originating_intent_id():
    base_request = replace(_request(), required_margin=Decimal("1000"))
    request = replace(
        base_request,
        order=replace(base_request.order, intent_id=None),
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_REQUEST_INVALID"):
        _build(_evidence(), request=request)


def test_builder_uses_trusted_evidence_and_separates_realized_from_unrealized_pnl():
    built = _build(_evidence(positions=_positions((_position(),))))
    assert built.snapshot.daily_pnl == Decimal("2500")
    assert built.snapshot.unrealized_loss == Decimal("1000")
    assert built.snapshot.currency == BASE_CURRENCY
    assert built.snapshot.current_position_exposure == Decimal("1000")
    assert built.intent.required_margin == Decimal("1000")
    assert built.intent.estimated_order_value is None
    assert built.context.reference_price == Decimal("100")


def test_empty_open_positions_are_only_accepted_with_all_three_complete_surfaces():
    built = _build(_evidence(positions=_positions(())))
    assert built.snapshot.current_portfolio_exposure == Decimal("0")
    assert built.snapshot.unrealized_loss == Decimal("0")


def test_mark_count_must_match_canonical_position_book():
    evidence = _evidence(positions=_positions((_position(),)))
    surfaces = tuple(
        replace(surface, row_count=0) if surface.surface is PositionSurface.MARKS else surface
        for surface in evidence.positions.surfaces
    )
    altered = replace(evidence, positions=replace(evidence.positions, surfaces=surfaces))
    with pytest.raises(LiveRiskEvidenceError, match="mark coverage does not match"):
        _build(altered)


def test_incomplete_holdings_surface_rejects_even_when_open_positions_are_empty():
    evidence = _evidence(
        positions=_positions((), surface_status=EvidenceStatus.INCOMPLETE)
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_EVIDENCE_INCOMPLETE"):
        _build(evidence)


def test_missing_daily_charge_coverage_rejects_pnl_authority():
    evidence = _evidence(pnl=_pnl(charges_daily=None))
    with pytest.raises(LiveRiskEvidenceError, match="DAILY_PNL_AUTHORITY_INCOMPLETE"):
        _build(evidence)


def test_explicit_unavailable_pnl_authority_is_not_treated_as_incomplete_zero():
    evidence = _evidence(pnl=_pnl(completeness=EvidenceStatus.UNAVAILABLE))
    with pytest.raises(LiveRiskEvidenceError, match="DAILY_PNL_AUTHORITY_UNAVAILABLE"):
        _build(evidence)


def test_assembly_claim_outside_trusted_clock_tolerance_rejects():
    evidence = _evidence(assembled_at=EVALUATED_AT - timedelta(seconds=6))
    with pytest.raises(
        LiveRiskEvidenceError, match="LIVE_RISK_ASSEMBLY_TIME_OUT_OF_TOLERANCE"
    ):
        _build(evidence)


def test_uncaptured_daily_activity_rejects_realized_pnl_authority():
    evidence = _evidence(pnl=_pnl(uncaptured_activity=("manual-trade",)))
    with pytest.raises(LiveRiskEvidenceError, match="DAILY_PNL_AUTHORITY_INCOMPLETE"):
        _build(evidence)


def test_wrong_trading_day_rejects_pnl_evidence():
    evidence = _evidence(pnl=_pnl(trading_day=date(2025, 12, 31)))
    with pytest.raises(LiveRiskEvidenceError, match="DAILY_PNL_TRADING_DAY_MISMATCH"):
        _build(evidence)


def test_missing_margin_authority_consistency_rejects():
    evidence = _evidence(margin_available=Decimal("100000"))
    altered = replace(
        evidence,
        financial_state=replace(
            evidence.financial_state,
            margin_available=Money(Decimal("99999"), BASE_CURRENCY),
        ),
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_EVIDENCE_INCONSISTENT"):
        _build(altered)


def test_stale_position_mark_rejects_entire_evidence_cut():
    old_mark = OBSERVED_AT - timedelta(minutes=10)
    evidence = _evidence(positions=_positions((_position(mark_observed_at=old_mark),)))
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_EVIDENCE_STALE"):
        _build(evidence)


def test_future_reference_price_rejects():
    future = ReferencePriceEvidence(
        instrument=_instrument(),
        price=Decimal("100"),
        observed_at=EVALUATED_AT + timedelta(seconds=1),
        source="synthetic-test-fixture",
        currency=BASE_CURRENCY,
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_EVIDENCE_FUTURE_DATED"):
        _build(_evidence(reference_price=future))


def test_request_margin_mismatch_rejects_instead_of_using_caller_claim():
    request = replace(_request(), required_margin=Decimal("999"))
    with pytest.raises(LiveRiskEvidenceError, match="MARGIN_REQUIREMENT_MISMATCH"):
        _build(_evidence(margin_required=Decimal("1000")), request=request)


def test_approved_evidence_result_carries_exact_request_and_evidence_binding():
    request = replace(_request(), required_margin=Decimal("1000"))
    evidence = _evidence(positions=_positions((_position(),)))
    result = evaluate_live_risk_evidence(
        request,
        engine=PreTradeRiskEngine(),
        policy=_policy(),
        evidence=evidence,
        trading_day=TRADING_DAY,
        trading_day_start_at=DAY_START_AT,
        evaluated_at=EVALUATED_AT,
    )
    assert result.decision is RiskDecision.APPROVE
    assert result.approval_binding is not None
    assert result.approval_binding.account_id == ACCOUNT
    assert result.approval_binding.connection_id == CONNECTION
    assert result.approval_binding.evidence_id == evidence.evidence_id
    assert result.approval_binding.request_fingerprint


def test_altered_request_invalidates_evidence_bound_risk_approval():
    request = replace(_request(), required_margin=Decimal("1000"))
    evidence = _evidence(positions=_positions((_position(),)))
    policy = _policy()
    result = evaluate_live_risk_evidence(
        request,
        engine=PreTradeRiskEngine(),
        policy=policy,
        evidence=evidence,
        trading_day=TRADING_DAY,
        trading_day_start_at=DAY_START_AT,
        evaluated_at=EVALUATED_AT,
    )
    assert result.approval_binding is not None
    inputs = _build(evidence, request=request)
    altered_order = replace(request.order, quantity=Decimal("11"))
    altered_request = replace(request, order=altered_order)
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_APPROVAL_BINDING_MISMATCH"):
        validate_live_risk_approval_binding(
            altered_request,
            result.approval_binding,
            policy=policy,
            evidence=evidence,
            inputs=inputs,
            evaluated_at=EVALUATED_AT,
        )


def test_changed_margin_claim_invalidates_evidence_bound_approval():
    request = replace(_request(), required_margin=Decimal("1000"))
    evidence = _evidence(positions=_positions((_position(),)))
    policy = _policy()
    result = evaluate_live_risk_evidence(
        request,
        engine=PreTradeRiskEngine(),
        policy=policy,
        evidence=evidence,
        trading_day=TRADING_DAY,
        trading_day_start_at=DAY_START_AT,
        evaluated_at=EVALUATED_AT,
    )
    assert result.approval_binding is not None
    altered_request = replace(request, required_margin=Decimal("1001"))
    inputs = _build(evidence, request=request)
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_APPROVAL_BINDING_MISMATCH"):
        validate_live_risk_approval_binding(
            altered_request,
            result.approval_binding,
            policy=policy,
            evidence=evidence,
            inputs=inputs,
            evaluated_at=EVALUATED_AT,
        )


def test_policy_rejects_unsupported_drawdown_and_concentration():
    request = replace(_request(), required_margin=Decimal("1000"))
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_POLICY_UNSUPPORTED"):
        build_live_risk_inputs(
            request,
            policy=replace(_policy(), limits=_limits(max_drawdown=Decimal("0.1"))),
            evidence=_evidence(),
            trading_day=TRADING_DAY,
            trading_day_start_at=DAY_START_AT,
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_POLICY_UNSUPPORTED"):
        build_live_risk_inputs(
            request,
            policy=replace(
                _policy(), limits=_limits(max_instrument_concentration=Decimal("0.5"))
            ),
            evidence=_evidence(),
            trading_day=TRADING_DAY,
            trading_day_start_at=DAY_START_AT,
            evaluated_at=EVALUATED_AT,
        )


def test_wrong_position_connection_fails_scope_validation():
    evidence = _evidence(
        positions=replace(_positions(), connection_id=BrokerConnectionId("other"))
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_SCOPE_MISMATCH"):
        _build(evidence)


def test_pnl_currency_mismatch_fails_closed():
    evidence = _evidence(
        pnl=_pnl(
            amount=Money(Decimal("2500"), "USD"),
            charges_daily=Money(Decimal("0"), "USD"),
        )
    )
    with pytest.raises(LiveRiskEvidenceError, match="LIVE_RISK_CURRENCY_MISMATCH"):
        _build(evidence)
