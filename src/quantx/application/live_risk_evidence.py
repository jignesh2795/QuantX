"""LIVE risk evidence contracts and deterministic snapshot construction.

This module contains no broker SDK, network, or credential behavior. The
connected broker adapter supplies immutable observations; this module validates
scope, completeness, currency, freshness, and derives the deterministic inputs
consumed by the existing pre-trade risk engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import (
    LiveRiskLimitsError,
    PreTradeRiskEngine,
    RiskApprovalBinding,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
    require_live_risk_limits,
)
from quantx.domain.risk_evidence import (
    EvidenceStatus,
    MarginEvidence,
    RealizedDailyPnlEvidence,
    RealizedPnlSource,
    ReferencePriceEvidence,
    WholeAccountPositionEvidence,
)
from quantx.domain.pending_scope import (
    PendingScopeGuard,
    PendingScopeResult,
    PendingScopeStatus,
)
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.idempotency.fingerprint import request_fingerprint

if TYPE_CHECKING:
    from quantx.application.live_risk import LiveRiskEvaluationInputs


class LiveRiskEvidenceError(ValueError):
    """A deterministic, fail-closed LIVE risk evidence validation failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


_MAX_ASSEMBLY_CLOCK_SKEW = timedelta(seconds=5)


def _status_error_code(
    status: EvidenceStatus,
    *,
    prefix: str,
    scope_mismatch_code: str = "LIVE_RISK_SCOPE_MISMATCH",
) -> str:
    """Map an explicit evidence status to a stable fail-closed reason."""

    if status is EvidenceStatus.UNAVAILABLE:
        return f"{prefix}_UNAVAILABLE"
    if status is EvidenceStatus.STALE:
        return f"{prefix}_STALE"
    if status is EvidenceStatus.SCOPE_MISMATCH:
        return scope_mismatch_code
    return f"{prefix}_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ConcurrencyAdmission:
    account_id: AccountId
    connection_id: BrokerConnectionId
    request_fingerprint: str
    admission_id: str
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("concurrency admission account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("concurrency admission connection_id must be BrokerConnectionId")
        _require_aware(self.acquired_at, "concurrency admission acquired_at")
        _require_aware(self.expires_at, "concurrency admission expires_at")
        if self.expires_at <= self.acquired_at:
            raise ValueError("concurrency admission expiry must follow acquisition")
        if not self.request_fingerprint.strip() or not self.admission_id.strip():
            raise ValueError("concurrency admission identity is required")


@runtime_checkable
class ConcurrencyGuard(Protocol):
    """Durable per-account admission/lease contract.

    A check-only implementation is insufficient: the admission must be
    exclusive and durable for the period defined by the implementation.
    """

    def acquire(
        self,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        *,
        request_fingerprint: str,
        acquired_at: datetime,
    ) -> ConcurrencyAdmission | None: ...

    def release(self, admission: ConcurrencyAdmission) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveRiskPolicy:
    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    base_currency: str
    limits: RiskLimits

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("LIVE risk policy account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("LIVE risk policy connection_id must be BrokerConnectionId")
        if not self.broker_id.strip():
            raise ValueError("LIVE risk policy broker_id is required")
        if not self.base_currency.strip():
            raise ValueError("LIVE risk policy base_currency is required")
        if type(self.limits) is not RiskLimits:
            raise ValueError("LIVE risk policy limits must be RiskLimits")


@dataclass(frozen=True, slots=True)
class LiveRiskEvidence:
    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    base_currency: str
    completeness: EvidenceStatus
    financial_state: AccountFinancialState
    financial_state_observed_at: datetime
    financial_state_completeness: EvidenceStatus
    broker_constraints: tuple[BrokerConstraint, ...]
    positions: WholeAccountPositionEvidence
    realized_daily_pnl: RealizedDailyPnlEvidence
    margin: MarginEvidence
    reference_price: ReferencePriceEvidence
    assembled_at: datetime
    evidence_id: str
    version: str
    provenance: str

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("LIVE evidence account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("LIVE evidence connection_id must be BrokerConnectionId")
        if (
            type(self.completeness) is not EvidenceStatus
            or type(self.financial_state_completeness) is not EvidenceStatus
        ):
            raise ValueError("LIVE evidence completeness must use EvidenceStatus")
        if type(self.positions) is not WholeAccountPositionEvidence:
            raise ValueError("LIVE evidence positions must use WholeAccountPositionEvidence")
        if type(self.realized_daily_pnl) is not RealizedDailyPnlEvidence:
            raise ValueError("LIVE evidence P&L must use RealizedDailyPnlEvidence")
        if type(self.margin) is not MarginEvidence:
            raise ValueError("LIVE evidence margin must use MarginEvidence")
        if type(self.reference_price) is not ReferencePriceEvidence:
            raise ValueError("LIVE evidence reference price must use ReferencePriceEvidence")
        if type(self.broker_constraints) is not tuple or any(
            type(item) is not BrokerConstraint for item in self.broker_constraints
        ):
            raise ValueError("broker_constraints must be an immutable tuple of BrokerConstraint")
        for name, value in (
            ("financial_state_observed_at", self.financial_state_observed_at),
            ("assembled_at", self.assembled_at),
        ):
            _require_aware(value, name)
        if not self.broker_id.strip() or not self.base_currency.strip():
            raise ValueError("LIVE evidence broker_id and base_currency are required")
        if not self.evidence_id.strip() or not self.version.strip() or not self.provenance.strip():
            raise ValueError("LIVE evidence identity, version, and provenance are required")
        if type(self.financial_state) is not AccountFinancialState:
            raise ValueError("LIVE evidence requires canonical AccountFinancialState")
        if self.financial_state.capital_source is not CapitalSourceType.LIVE_BROKER:
            raise ValueError("LIVE evidence financial state must come from LIVE_BROKER")
        if type(self.broker_constraints) is not tuple:
            raise ValueError("broker_constraints must be an immutable tuple")


@runtime_checkable
class LiveRiskEvidenceSource(Protocol):
    """Implemented by the exact registered broker adapter used for submission."""

    def observe_live_risk_evidence(
        self,
        request: ApprovedExecutionRequest,
        *,
        evaluated_at: datetime,
    ) -> LiveRiskEvidence: ...


def build_live_risk_inputs(
    request: ApprovedExecutionRequest,
    *,
    policy: LiveRiskPolicy,
    evidence: LiveRiskEvidence,
    trading_day: date,
    trading_day_start_at: datetime,
    evaluated_at: datetime,
) -> LiveRiskEvaluationInputs:
    """Validate one complete evidence envelope and derive risk engine inputs.

    Caller values for financial state, exposure, reference price, order value,
    and P&L are never used as authorities. A mismatch between the request's
    declared margin and the broker authority is rejected rather than silently
    selecting one value.
    """
    from quantx.application.live_risk import LiveRiskEvaluationInputs
    from quantx.domain.enums import OrderSide, OrderType

    now = _aware_utc(evaluated_at, "trusted evaluation instant")
    if type(policy) is not LiveRiskPolicy or type(evidence) is not LiveRiskEvidence:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_INVALID", "unsupported policy/evidence type"
        )
    try:
        limits = require_live_risk_limits(policy.limits)
    except LiveRiskLimitsError as exc:
        raise LiveRiskEvidenceError("LIVE_RISK_POLICY_INVALID", str(exc)) from None
    if limits.max_drawdown is not None:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_POLICY_UNSUPPORTED", "max_drawdown has no authoritative equity/HWM source"
        )
    if limits.max_instrument_concentration is not None:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_POLICY_UNSUPPORTED",
            "max_instrument_concentration has no gross-basis contract",
        )
    if request.execution_context.execution_mode is not ExecutionMode.LIVE:
        raise LiveRiskEvidenceError("LIVE_RISK_SCOPE_MISMATCH", "request is not LIVE")
    if (
        request.execution_context.account_id != policy.account_id
        or request.execution_context.broker_connection_id != policy.connection_id
        or evidence.account_id != policy.account_id
        or evidence.connection_id != policy.connection_id
        or evidence.positions.account_id != policy.account_id
        or evidence.positions.connection_id != policy.connection_id
        or evidence.realized_daily_pnl.account_id != policy.account_id
        or evidence.realized_daily_pnl.connection_id != policy.connection_id
        or evidence.margin.account_id != policy.account_id
        or evidence.margin.connection_id != policy.connection_id
    ):
        raise LiveRiskEvidenceError(
            "LIVE_RISK_SCOPE_MISMATCH", "request and evidence account/connection differ"
        )
    if (
        evidence.broker_id != policy.broker_id
        or evidence.realized_daily_pnl.broker_id != policy.broker_id
    ):
        raise LiveRiskEvidenceError("LIVE_RISK_SCOPE_MISMATCH", "broker identity differs")
    if (
        type(request.required_margin) is not Decimal
        or not request.required_margin.is_finite()
        or request.required_margin != evidence.margin.required_margin.amount
    ):
        raise LiveRiskEvidenceError(
            "MARGIN_REQUIREMENT_MISMATCH",
            "request-declared margin differs from authoritative broker margin",
        )
    if evidence.completeness is not EvidenceStatus.COMPLETE:
        code = _status_error_code(evidence.completeness, prefix="LIVE_RISK_EVIDENCE")
        raise LiveRiskEvidenceError(code, "top-level evidence is not COMPLETE")
    if evidence.financial_state_completeness is not EvidenceStatus.COMPLETE:
        code = _status_error_code(
            evidence.financial_state_completeness, prefix="LIVE_RISK_FINANCIAL_STATE"
        )
        raise LiveRiskEvidenceError(code, "account financial state is not COMPLETE")

    pnl = evidence.realized_daily_pnl
    if pnl.source not in {
        RealizedPnlSource.BROKER_REPORTED,
        RealizedPnlSource.QUANTX_LEDGER_WITH_BROKER_TRADE_BOOK,
    }:
        raise LiveRiskEvidenceError("DAILY_PNL_AUTHORITY_UNAVAILABLE", "unapproved P&L source")
    if pnl.completeness is not EvidenceStatus.COMPLETE:
        code = _status_error_code(pnl.completeness, prefix="DAILY_PNL_AUTHORITY")
        raise LiveRiskEvidenceError(code, "realized P&L evidence is not COMPLETE")
    pnl_amount = pnl.amount
    if pnl_amount is None:
        raise LiveRiskEvidenceError(
            "DAILY_PNL_AUTHORITY_UNAVAILABLE",
            "realized P&L evidence has no authoritative amount",
        )
    if pnl.scope != "WHOLE_ACCOUNT":
        raise LiveRiskEvidenceError(
            "DAILY_PNL_AUTHORITY_INCOMPLETE", "realized P&L is not whole-account evidence"
        )
    if pnl.charges_daily is None:
        raise LiveRiskEvidenceError(
            "DAILY_PNL_AUTHORITY_INCOMPLETE", "daily charges are not covered by the authority"
        )
    if pnl.charges_daily.currency != policy.base_currency:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_CURRENCY_MISMATCH", "daily charges currency differs from base currency"
        )
    if pnl.uncaptured_activity:
        raise LiveRiskEvidenceError(
            "DAILY_PNL_AUTHORITY_INCOMPLETE", "daily P&L reports uncaptured account activity"
        )
    expected_day_start = _aware_utc(trading_day_start_at, "trusted trading-day start instant")
    if (
        pnl.trading_day != trading_day
        or _aware_utc(pnl.day_start_at, "P&L day_start_at") != expected_day_start
    ):
        raise LiveRiskEvidenceError(
            "DAILY_PNL_TRADING_DAY_MISMATCH",
            "P&L trading day or session start differs from the trusted calendar",
        )
    if pnl.day_start_at > pnl.as_of or pnl.as_of > now:
        raise LiveRiskEvidenceError(
            "DAILY_PNL_STALE", "P&L timestamps are inconsistent or future-dated"
        )

    position_book = evidence.positions
    if position_book.completeness is not EvidenceStatus.COMPLETE:
        code = _status_error_code(position_book.completeness, prefix="LIVE_RISK_POSITION_BOOK")
        raise LiveRiskEvidenceError(code, "whole-account position book is not COMPLETE")
    if position_book.blockers:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_POSITION_BOOK_INCOMPLETE",
            "whole-account position book declares provider-semantic blockers",
        )
    required_surfaces = {"POSITIONS", "HOLDINGS", "MARKS"}
    surfaces_by_name = {surface.surface.value: surface for surface in position_book.surfaces}
    if set(surfaces_by_name) != required_surfaces:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_INCOMPLETE",
            "POSITIONS, HOLDINGS, and MARKS surfaces must all be present",
        )
    if any(surface.status is not EvidenceStatus.COMPLETE for surface in position_book.surfaces):
        failing = next(
            surface
            for surface in position_book.surfaces
            if surface.status is not EvidenceStatus.COMPLETE
        )
        code = _status_error_code(failing.status, prefix="LIVE_RISK_POSITION_SURFACE")
        raise LiveRiskEvidenceError(code, f"{failing.surface.value} surface is not COMPLETE")
    if surfaces_by_name["MARKS"].row_count != len(position_book.positions):
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_INCOMPLETE",
            "mark coverage does not match the canonical position book",
        )
    margin = evidence.margin
    if margin.completeness is not EvidenceStatus.COMPLETE:
        code = _status_error_code(margin.completeness, prefix="LIVE_RISK_MARGIN")
        raise LiveRiskEvidenceError(code, "margin evidence is not COMPLETE")
    if evidence.reference_price.instrument.instrument_id != request.order.instrument:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_SCOPE_MISMATCH", "reference price is for a different instrument"
        )

    currency = policy.base_currency
    if evidence.base_currency != currency:
        raise LiveRiskEvidenceError("LIVE_RISK_SCOPE_MISMATCH", "base currency differs")
    for value, name in (
        (pnl_amount, "realized P&L"),
        (margin.required_margin, "required margin"),
        (margin.available_margin, "available margin"),
        (evidence.reference_price, "reference price"),
    ):
        if value.currency != currency:
            raise LiveRiskEvidenceError("LIVE_RISK_CURRENCY_MISMATCH", f"{name} currency differs")
    financial = evidence.financial_state
    money_fields = (
        financial.cash_balance,
        financial.available_cash,
        financial.blocked_cash,
        financial.margin_used,
        financial.margin_available,
        financial.buying_power,
    )
    if any(item.currency != currency for item in money_fields):
        raise LiveRiskEvidenceError(
            "LIVE_RISK_CURRENCY_MISMATCH", "account financial state currency differs"
        )
    if financial.margin_available.amount != margin.available_margin.amount:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_INCONSISTENT",
            "margin authority and account financial state disagree",
        )
    if margin.required_margin.currency != currency:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_CURRENCY_MISMATCH", "required margin currency differs"
        )
    if any(position.currency != currency for position in position_book.positions):
        raise LiveRiskEvidenceError(
            "LIVE_RISK_CURRENCY_MISMATCH", "a position currency differs from base currency"
        )

    age_limit = limits.max_snapshot_age
    if age_limit is None:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_POLICY_UNSUPPORTED", "max_snapshot_age is mandatory in LIVE"
        )
    instants = [
        evidence.financial_state_observed_at,
        position_book.observed_at,
        pnl.as_of,
        margin.observed_at,
        evidence.reference_price.observed_at,
        *(surface.observed_at for surface in position_book.surfaces),
        *(position.mark_observed_at for position in position_book.positions),
    ]
    canonical_instants = [_aware_utc(value, "evidence component instant") for value in instants]
    if any(value > now for value in canonical_instants):
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_FUTURE_DATED", "a component is future-dated"
        )
    evidence_cut = min(canonical_instants)
    if now - evidence_cut > age_limit:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_STALE", "evidence cut exceeds max_snapshot_age"
        )
    assembled = _aware_utc(evidence.assembled_at, "evidence assembled_at")
    assembly_skew = abs(now - assembled)
    if assembled > now:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_FUTURE_DATED", "assembly time is future-dated"
        )
    if assembly_skew > _MAX_ASSEMBLY_CLOCK_SKEW:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_ASSEMBLY_TIME_OUT_OF_TOLERANCE",
            "evidence assembly time differs from the trusted clock by more than five seconds",
        )

    target_instrument = request.order.instrument
    target_product = request.product
    if target_product is None:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_SCOPE_MISMATCH", "a canonical product is required for LIVE risk valuation"
        )
    current_position_exposure = Decimal("0")
    current_instrument_exposure = Decimal("0")
    current_portfolio_exposure = Decimal("0")
    total_unrealized_pnl = Decimal("0")
    canonical_instrument = evidence.reference_price.instrument
    for position in position_book.positions:
        instrument = position.instrument
        if instrument.currency != currency:
            raise LiveRiskEvidenceError(
                "LIVE_RISK_CURRENCY_MISMATCH", "canonical instrument currency differs"
            )
        signed_notional = position.quantity * position.mark_price * instrument.multiplier
        unrealized = (
            (position.mark_price - position.average_price)
            * position.quantity
            * instrument.multiplier
        )
        current_portfolio_exposure += signed_notional
        total_unrealized_pnl += unrealized
        if instrument.instrument_id == target_instrument:
            current_instrument_exposure += signed_notional
            if position.product == target_product:
                current_position_exposure += signed_notional

    # The reference-price instrument is canonical for the request's target.
    order = request.order
    if order.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        if order.limit_price is None or type(order.limit_price) is not Decimal:
            raise LiveRiskEvidenceError(
                "LIVE_ORDER_PRICE_UNAVAILABLE", "limit order price is missing"
            )
        trusted_reference_price = order.limit_price
    else:
        trusted_reference_price = evidence.reference_price.price

    if type(trusted_reference_price) is not Decimal or not trusted_reference_price.is_finite():
        raise LiveRiskEvidenceError(
            "LIVE_ORDER_PRICE_UNAVAILABLE", "trusted order price is invalid"
        )
    if trusted_reference_price <= 0:
        raise LiveRiskEvidenceError(
            "LIVE_ORDER_PRICE_UNAVAILABLE", "trusted order price is not positive"
        )
    if order.side not in {OrderSide.BUY, OrderSide.SELL}:
        raise LiveRiskEvidenceError("LIVE_RISK_EVIDENCE_INVALID", "unsupported order side")

    # An order detached from its originating intent cannot be safely bound
    # back to the strategy-level risk request. Fail closed rather than passing
    # None into a field whose domain contract requires an immutable UUID.
    intent_id = order.intent_id
    if intent_id is None:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_REQUEST_INVALID", "order must retain its originating intent id"
        )

    # request.required_margin is validated against the broker authority above.
    intent = TradeIntent(
        instrument=order.instrument,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
        time_in_force=order.time_in_force,
        required_margin=margin.required_margin.amount,
        estimated_order_value=None,
        required_capabilities=order.required_capabilities,
        approval_required=False,
        strategy_id=order.strategy_id,
        strategy_version=order.strategy_version,
        execution_context=request.execution_context,
        intent_id=intent_id,
        product=request.product,
        position_effect=request.position_effect,
    )
    context = RiskContext(
        instrument=canonical_instrument,
        financial_state=financial,
        broker_constraints=evidence.broker_constraints,
        reference_price=trusted_reference_price,
        product=request.product,
        effective_position_effect=request.effective_position_effect,
        market_pack_id=request.execution_context.market_pack_id,
        rule_version=request.execution_context.rule_version,
        instrument_resolution=request.instrument_resolution,
    )
    snapshot = RiskSnapshot(
        observed_at=evidence_cut,
        current_position_exposure=current_position_exposure,
        current_instrument_exposure=current_instrument_exposure,
        current_portfolio_exposure=current_portfolio_exposure,
        available_margin=margin.available_margin.amount,
        required_margin=margin.required_margin.amount,
        daily_pnl=pnl_amount.amount,
        equity=None,
        high_water_mark=None,
        unrealized_loss=max(Decimal("0"), -total_unrealized_pnl),
        currency=currency,
    )
    return LiveRiskEvaluationInputs(
        intent=intent,
        context=context,
        snapshot=snapshot,
        claimed_evaluated_at=now,
    )


def validate_live_risk_approval_binding(
    request: ApprovedExecutionRequest,
    binding: RiskApprovalBinding,
    *,
    policy: LiveRiskPolicy,
    evidence: LiveRiskEvidence,
    inputs: LiveRiskEvaluationInputs,
    evaluated_at: datetime,
) -> None:
    """Reject an approval reused with a changed request or different evidence."""

    instant = _aware_utc(evaluated_at, "trusted evaluation instant")
    expected = (
        binding.account_id == policy.account_id
        and binding.connection_id == policy.connection_id
        and binding.currency == policy.base_currency
        and binding.trading_day == evidence.realized_daily_pnl.trading_day
        and binding.evidence_id == evidence.evidence_id
        and binding.evidence_cut == inputs.snapshot.observed_at
        and binding.evaluated_at == instant
        and binding.request_fingerprint == request_fingerprint(request)
        and type(request.required_margin) is Decimal
        and request.required_margin.is_finite()
        and request.required_margin == evidence.margin.required_margin.amount
    )
    if not expected:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_APPROVAL_BINDING_MISMATCH",
            "request fingerprint, scope, time, currency, or evidence identity differs",
        )


def evaluate_live_risk_evidence(
    request: ApprovedExecutionRequest,
    *,
    engine: PreTradeRiskEngine,
    policy: LiveRiskPolicy,
    evidence: LiveRiskEvidence,
    trading_day: date,
    trading_day_start_at: datetime,
    evaluated_at: datetime,
) -> RiskResult:
    """Evaluate validated evidence and bind any approval to this exact request."""

    if type(engine) is not PreTradeRiskEngine:
        raise LiveRiskEvidenceError(
            "LIVE_RISK_EVIDENCE_INVALID", "engine must be the canonical PreTradeRiskEngine"
        )
    inputs = build_live_risk_inputs(
        request,
        policy=policy,
        evidence=evidence,
        trading_day=trading_day,
        trading_day_start_at=trading_day_start_at,
        evaluated_at=evaluated_at,
    )
    result = engine.evaluate_with_limits(
        inputs.intent,
        inputs.context,
        limits=require_live_risk_limits(policy.limits),
        snapshot=inputs.snapshot,
        evaluated_at=inputs.claimed_evaluated_at,
    )
    if result.decision is not RiskDecision.APPROVE:
        return result
    binding = RiskApprovalBinding(
        account_id=policy.account_id,
        connection_id=policy.connection_id,
        currency=policy.base_currency,
        trading_day=trading_day,
        evidence_id=evidence.evidence_id,
        evidence_cut=inputs.snapshot.observed_at,
        evaluated_at=_aware_utc(evaluated_at, "trusted evaluation instant"),
        request_fingerprint=request_fingerprint(request),
    )
    bound_result = replace(result, approval_binding=binding)
    validate_live_risk_approval_binding(
        request,
        binding,
        policy=policy,
        evidence=evidence,
        inputs=inputs,
        evaluated_at=evaluated_at,
    )
    return bound_result


def _require_aware(value: datetime, name: str) -> None:
    """Reject naive timestamps in evidence value objects."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _aware_utc(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LiveRiskEvidenceError("LIVE_RISK_EVIDENCE_INVALID", f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ConcurrencyAdmission",
    "ConcurrencyGuard",
    "LiveRiskEvidence",
    "LiveRiskEvidenceError",
    "LiveRiskEvidenceSource",
    "LiveRiskPolicy",
    "PendingScopeGuard",
    "PendingScopeResult",
    "PendingScopeStatus",
    "build_live_risk_inputs",
    "evaluate_live_risk_evidence",
    "validate_live_risk_approval_binding",
]
