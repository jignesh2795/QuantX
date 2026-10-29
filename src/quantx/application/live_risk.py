"""LIVE pre-trade risk evaluator composition with an optional evidence authority.

The evaluator supports exactly one evidence mode per instance. In callback
mode a provider supplies risk inputs and a timestamp claim; the evaluator reads
one trusted clock and passes only that reading to the deterministic domain
engine as the evaluation instant. This prevents a provider from making an
already-old ``snapshot.observed_at`` pass freshness merely by claiming a recent
evaluation time. Callback mode does not authenticate the accuracy or provenance
of the supplied evidence, and it is always reported as non-authoritative.

In authority mode the evaluator asks an application-owned
``LiveRiskEvidenceAuthority`` to collect evidence and bind it to the exact
account, broker connection, broker client, transport, approved request, and
trusted capture instant. The authority returns an HMAC-sealed authorization
that the evaluator verifies before the same domain engine runs. Missing,
foreign, contradictory, stale, future-dated, or incomplete evidence never
reaches the engine as approval.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import Clock
from quantx.domain.enums import OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.finance import CapitalSourceType
from quantx.domain.instrument_registry import InstrumentResolution
from quantx.domain.instruments import MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import (
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
    require_live_risk_limits,
)
from quantx.domain.value_objects import Money, canonical_decimal, canonical_instant

# Fixed policy threshold for how far a provider timestamp claim may sit from the
# trusted clock. It bounds claim credibility only: freshness is always computed
# from the trusted reading, so this value never widens a snapshot's age budget.
_MAX_LIVE_RISK_CLOCK_SKEW = timedelta(seconds=5)

_CLAIM_INVALID_REASON = "LIVE_CLOCK_CLAIM_INVALID: the provider timestamp claim is unusable"
_CLAIM_OUT_OF_TOLERANCE_REASON = (
    "LIVE_CLOCK_CLAIM_OUT_OF_TOLERANCE: the provider timestamp claim is more than "
    "five seconds from the trusted clock"
)
_CLOCK_UNAVAILABLE_REASON = "LIVE_CLOCK_UNAVAILABLE: the trusted clock could not be read"
_CLOCK_INVALID_REASON = "LIVE_CLOCK_INVALID: the trusted clock returned an unusable instant"


@dataclass(frozen=True, slots=True)
class LiveRiskEvaluationInputs:
    """Explicit inputs for one LIVE risk evaluation.

    ``claimed_evaluated_at`` is the provider's claim about when it assembled
    this evidence. It is validated against the evaluator's trusted clock and
    never becomes the freshness instant: the trusted reading does.
    """

    intent: TradeIntent
    context: RiskContext
    snapshot: RiskSnapshot
    claimed_evaluated_at: datetime


def _utc_instant(value: object) -> datetime | None:
    """Return ``value`` as a UTC instant, or ``None`` when it is not a safe time.

    A naive value is rejected instead of being assumed to be UTC, and a
    datetime subclass is rejected because it is a different time contract.
    """
    if type(value) is not datetime:
        return None
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)
    except Exception:
        return None


def _reject(inputs: LiveRiskEvaluationInputs, reason: str) -> RiskResult:
    """Reject while retaining the instrument resolution this evaluation consumed."""
    return RiskResult(
        RiskDecision.REJECT,
        reason,
        instrument_resolution=inputs.context.instrument_resolution,
    )


_REQUEST_MISMATCH_REASON = (
    "LIVE_RISK_REQUEST_MISMATCH: risk inputs do not match the approved execution request"
)


def _same_instrument_resolution(
    left: InstrumentResolution | None,
    right: InstrumentResolution | None,
) -> bool:
    if left is None or right is None:
        return left is right
    if type(left) is not InstrumentResolution or type(right) is not InstrumentResolution:
        return False
    try:
        return left.identity_payload() == right.identity_payload()
    except Exception:
        return False


def _risk_inputs_match_request(
    request: ApprovedExecutionRequest,
    inputs: LiveRiskEvaluationInputs,
) -> bool:
    """Prove the supplied risk intent/context describes the exact approved request.

    This is identity consistency only. It does not establish that balances,
    positions, P&L, quote timestamps, or snapshots came from an authoritative
    source; that separate provenance gap keeps public LIVE readiness unclaimed.
    """
    if (
        type(inputs.intent) is not TradeIntent
        or type(inputs.context) is not RiskContext
        or type(inputs.snapshot) is not RiskSnapshot
    ):
        return False

    intent = inputs.intent
    context = inputs.context
    snapshot = inputs.snapshot
    order = request.order
    execution_context = request.execution_context
    if (
        context.account_id != execution_context.account_id
        or context.portfolio_id != execution_context.portfolio_id
        or context.broker_connection_id != execution_context.broker_connection_id
        or snapshot.account_id != execution_context.account_id
        or snapshot.portfolio_id != execution_context.portfolio_id
        or snapshot.broker_connection_id != execution_context.broker_connection_id
        or context.financial_state.capital_source is not CapitalSourceType.LIVE_BROKER
        or intent.instrument != order.instrument
        or intent.intent_id != order.intent_id
        or intent.side is not order.side
        or intent.quantity != order.quantity
        or intent.order_type is not order.order_type
        or intent.limit_price != order.limit_price
        or intent.stop_price != order.stop_price
        or intent.time_in_force is not order.time_in_force
        or intent.required_capabilities != order.required_capabilities
        or intent.required_margin != request.required_margin
        or intent.strategy_id != order.strategy_id
        or intent.strategy_version != order.strategy_version
        or intent.product != request.product
        or intent.product != order.product
        or intent.position_effect != request.position_effect
        or intent.position_effect != order.position_effect
        or intent.execution_context != request.execution_context
        or context.instrument.instrument_id != order.instrument
        or context.instrument.market != request.execution_context.market
        or (
            context.instrument_resolution is not None
            and context.instrument != context.instrument_resolution.instrument
        )
        or context.product != request.product
        or context.effective_position_effect != request.effective_position_effect
        or context.market_pack_id != request.execution_context.market_pack_id
        or context.rule_version != request.execution_context.rule_version
        or not _same_instrument_resolution(
            context.instrument_resolution, request.instrument_resolution
        )
    ):
        return False

    return True


class LiveRiskEvidenceField(StrEnum):
    """One mandatory risk-evidence value a LIVE evaluation may consume."""

    CASH_BALANCE = "cash_balance"
    AVAILABLE_CASH = "available_cash"
    BLOCKED_CASH = "blocked_cash"
    MARGIN_USED = "margin_used"
    MARGIN_AVAILABLE = "margin_available"
    BUYING_POWER = "buying_power"
    CURRENT_POSITION_EXPOSURE = "current_position_exposure"
    CURRENT_INSTRUMENT_EXPOSURE = "current_instrument_exposure"
    CURRENT_PORTFOLIO_EXPOSURE = "current_portfolio_exposure"
    DAILY_PNL = "daily_pnl"
    EQUITY = "equity"
    HIGH_WATER_MARK = "high_water_mark"


_FINANCIAL_EVIDENCE_FIELDS: tuple[LiveRiskEvidenceField, ...] = (
    LiveRiskEvidenceField.CASH_BALANCE,
    LiveRiskEvidenceField.AVAILABLE_CASH,
    LiveRiskEvidenceField.BLOCKED_CASH,
    LiveRiskEvidenceField.MARGIN_USED,
    LiveRiskEvidenceField.MARGIN_AVAILABLE,
    LiveRiskEvidenceField.BUYING_POWER,
)


def required_live_risk_evidence_fields(limits: RiskLimits) -> frozenset[LiveRiskEvidenceField]:
    """Return the evidence fields the configured LIVE limits actually consume.

    The six account-financial values are always required because the existing
    ``RiskContext`` contract cannot be built without them. Every additional
    field is required only when its check is enabled; a disabled check never
    turns an unavailable value into a requirement.
    """
    required = set(_FINANCIAL_EVIDENCE_FIELDS)
    if limits.max_position_notional is not None:
        required.add(LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE)
    if limits.max_portfolio_exposure is not None:
        required.add(LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE)
    if limits.max_instrument_concentration is not None:
        required.add(LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE)
        required.add(LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE)
    if limits.max_daily_loss is not None:
        required.add(LiveRiskEvidenceField.DAILY_PNL)
    if limits.max_drawdown is not None:
        required.add(LiveRiskEvidenceField.EQUITY)
        required.add(LiveRiskEvidenceField.HIGH_WATER_MARK)
    return frozenset(required)


@dataclass(frozen=True, slots=True)
class LiveRiskEvidenceObservation:
    """One source observation with the instant the source captured it."""

    value: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if type(self.value) is not Decimal or not self.value.is_finite():
            raise ValueError("risk evidence observation value must be a finite Decimal")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("risk evidence observation instant must be timezone-aware")


@dataclass(frozen=True, slots=True)
class LiveRiskEvidence:
    """One source's evidence candidate before application-owned validation.

    This is deliberately a neutral record, not an authorization. A source may
    construct it, but only :class:`LiveRiskEvidenceAuthority` can bind it to
    the configured account/connection/client/transport and mint admission.
    """

    source_id: str
    broker_client_id: str | None
    account_id: AccountId | None
    broker_connection_id: BrokerConnectionId | None
    transport: object | None
    identity_observed_at: datetime | None
    context: RiskContext | None
    snapshot: RiskSnapshot | None
    observations: Mapping[LiveRiskEvidenceField, LiveRiskEvidenceObservation] = field(
        default_factory=dict
    )
    reference_price: Decimal | None = None
    unavailable_fields: tuple[LiveRiskEvidenceField, ...] = ()
    contradictions: tuple[str, ...] = ()
    message: str = ""


@runtime_checkable
class LiveRiskEvidenceSource(Protocol):
    """Application-wired source of broker-bound LIVE risk evidence.

    ``supported_fields`` declares what the source can ever provide. The
    authority compares it with the fields the configured limits require; a
    source that cannot satisfy them never makes LIVE admission available.
    """

    @property
    def source_id(self) -> str: ...

    @property
    def supported_fields(self) -> frozenset[LiveRiskEvidenceField]: ...

    def collect(self, request: ApprovedExecutionRequest) -> LiveRiskEvidence: ...


@dataclass(frozen=True, slots=True)
class LiveRiskEvidenceAuthorization:
    """Per-authority HMAC seal over one request's evidence inputs.

    The seal proves the inputs were minted by this authority instance; it does
    not track replay. Each admission call mints a fresh seal, and the evaluator
    verifies it against the exact request and inputs before the engine runs.
    """

    client_order_id: UUID
    evidence_digest: str
    seal: str = field(repr=False)


_SOURCE_UNAVAILABLE_REASON = (
    "LIVE_RISK_EVIDENCE_SOURCE_UNAVAILABLE: the configured source cannot provide "
    "every mandatory LIVE risk evidence field"
)
_EVIDENCE_UNAVAILABLE_REASON = (
    "LIVE_RISK_EVIDENCE_UNAVAILABLE: the authoritative LIVE risk evidence source "
    "returned no usable evidence"
)
_EVIDENCE_IDENTITY_REASON = (
    "LIVE_RISK_EVIDENCE_IDENTITY_MISMATCH: evidence does not match the configured "
    "account, connection, broker client, or transport"
)
_EVIDENCE_REQUEST_REASON = (
    "LIVE_RISK_EVIDENCE_REQUEST_MISMATCH: evidence does not describe the approved execution request"
)
_EVIDENCE_INCOMPLETE_REASON = (
    "LIVE_RISK_EVIDENCE_INCOMPLETE: mandatory LIVE risk evidence fields are unavailable"
)
_EVIDENCE_CONTRADICTION_REASON = (
    "LIVE_RISK_EVIDENCE_CONTRADICTION: evidence contains contradictory observations"
)
_EVIDENCE_FUTURE_REASON = (
    "LIVE_RISK_EVIDENCE_FUTURE_DATED: evidence was observed after the trusted capture instant"
)
_EVIDENCE_STALE_REASON = (
    "LIVE_RISK_EVIDENCE_STALE: evidence is older than the configured maximum snapshot age"
)
_EVIDENCE_AUTHORIZATION_REASON = (
    "LIVE_RISK_EVIDENCE_AUTHORIZATION_INVALID: the LIVE risk evidence authorization "
    "is not valid for this request"
)
_EVIDENCE_CLOCK_UNAVAILABLE_REASON = (
    "LIVE_RISK_EVIDENCE_CLOCK_UNAVAILABLE: the trusted clock could not be read"
)
_EVIDENCE_CLOCK_INVALID_REASON = (
    "LIVE_RISK_EVIDENCE_CLOCK_INVALID: the trusted clock returned an unusable instant"
)


def _intent_for_request(request: ApprovedExecutionRequest) -> TradeIntent | None:
    """Build the exact intent the approved request already carries.

    The approved request is the authority for side, quantity, prices, product,
    effect and context; this helper never invents a value the request does not
    contain. An order without a canonical intent id cannot be matched to the
    evidence, so it stays unknown instead of receiving a fresh id.
    """
    order = request.order
    if type(order.intent_id) is not UUID:
        return None
    return TradeIntent(
        instrument=order.instrument,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
        time_in_force=order.time_in_force,
        required_margin=request.required_margin,
        required_capabilities=order.required_capabilities,
        execution_context=request.execution_context,
        intent_id=order.intent_id,
        product=request.product,
        position_effect=request.position_effect,
        strategy_id=order.strategy_id,
        strategy_version=order.strategy_version,
    )


def _money_digest(value: Money) -> str:
    return f"{canonical_decimal(value.amount)}:{value.currency}"


def _decimal_digest(value: Decimal | None) -> str:
    return "none" if value is None else canonical_decimal(value)


def _instant_digest(value: datetime) -> str:
    return canonical_instant(value)


def _resolution_digest(value: InstrumentResolution | None) -> str:
    if value is None:
        return "none"
    return repr(value.identity_payload())


def _inputs_digest(client_order_id: UUID, inputs: LiveRiskEvaluationInputs) -> str:
    """Canonical digest binding one authorization to the exact inputs it minted."""
    intent = inputs.intent
    context = inputs.context
    snapshot = inputs.snapshot
    financial = context.financial_state
    parts = [
        f"client_order_id={client_order_id}",
        f"intent_id={intent.intent_id}",
        f"intent_instrument={intent.instrument}",
        f"intent_side={intent.side}",
        f"intent_quantity={_decimal_digest(intent.quantity)}",
        f"intent_order_type={intent.order_type}",
        f"intent_limit={_decimal_digest(intent.limit_price)}",
        f"intent_stop={_decimal_digest(intent.stop_price)}",
        f"intent_tif={intent.time_in_force}",
        f"intent_margin={_decimal_digest(intent.required_margin)}",
        f"intent_value={_decimal_digest(intent.estimated_order_value)}",
        f"intent_capabilities={sorted(intent.required_capabilities)}",
        f"intent_approval={intent.approval_required}",
        f"intent_strategy={intent.strategy_id}:{intent.strategy_version}",
        f"intent_product={intent.product}",
        f"intent_effect={intent.position_effect}",
        f"intent_context={intent.execution_context}",
        f"context_account={context.account_id}",
        f"context_portfolio={context.portfolio_id}",
        f"context_connection={context.broker_connection_id}",
        f"context_instrument={context.instrument.instrument_id}",
        f"context_market={context.instrument.market.to_payload()}",
        f"context_reference={_decimal_digest(context.reference_price)}",
        f"context_product={context.product}",
        f"context_effect={context.effective_position_effect}",
        f"context_pack={context.market_pack_id}",
        f"context_rule={context.rule_version}",
        f"context_resolution={_resolution_digest(context.instrument_resolution)}",
        f"cash_balance={_money_digest(financial.cash_balance)}",
        f"available_cash={_money_digest(financial.available_cash)}",
        f"blocked_cash={_money_digest(financial.blocked_cash)}",
        f"margin_used={_money_digest(financial.margin_used)}",
        f"margin_available={_money_digest(financial.margin_available)}",
        f"buying_power={_money_digest(financial.buying_power)}",
        f"snapshot_at={_instant_digest(snapshot.observed_at)}",
        f"snapshot_position={_decimal_digest(snapshot.current_position_exposure)}",
        f"snapshot_instrument={_decimal_digest(snapshot.current_instrument_exposure)}",
        f"snapshot_portfolio={_decimal_digest(snapshot.current_portfolio_exposure)}",
        f"snapshot_available_margin={_decimal_digest(snapshot.available_margin)}",
        f"snapshot_required_margin={_decimal_digest(snapshot.required_margin)}",
        f"snapshot_daily_pnl={_decimal_digest(snapshot.daily_pnl)}",
        f"snapshot_equity={_decimal_digest(snapshot.equity)}",
        f"snapshot_high_water_mark={_decimal_digest(snapshot.high_water_mark)}",
        f"snapshot_account={snapshot.account_id}",
        f"snapshot_portfolio_id={snapshot.portfolio_id}",
        f"snapshot_connection={snapshot.broker_connection_id}",
        f"claimed_at={_instant_digest(inputs.claimed_evaluated_at)}",
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _expected_reference_price(request: ApprovedExecutionRequest) -> Decimal | None:
    """Limit orders may use their limit price; market orders stay unknown."""
    order = request.order
    if order.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        return order.limit_price
    return None


def _financial_expected(
    context: RiskContext, evidence_field: LiveRiskEvidenceField
) -> Decimal | None:
    financial = context.financial_state
    return {
        LiveRiskEvidenceField.CASH_BALANCE: financial.cash_balance.amount,
        LiveRiskEvidenceField.AVAILABLE_CASH: financial.available_cash.amount,
        LiveRiskEvidenceField.BLOCKED_CASH: financial.blocked_cash.amount,
        LiveRiskEvidenceField.MARGIN_USED: financial.margin_used.amount,
        LiveRiskEvidenceField.MARGIN_AVAILABLE: financial.margin_available.amount,
        LiveRiskEvidenceField.BUYING_POWER: financial.buying_power.amount,
    }.get(evidence_field)


def _snapshot_expected(
    snapshot: RiskSnapshot, evidence_field: LiveRiskEvidenceField
) -> Decimal | None:
    return {
        LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE: snapshot.current_position_exposure,
        LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE: snapshot.current_instrument_exposure,
        LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE: snapshot.current_portfolio_exposure,
        LiveRiskEvidenceField.DAILY_PNL: snapshot.daily_pnl,
        LiveRiskEvidenceField.EQUITY: snapshot.equity,
        LiveRiskEvidenceField.HIGH_WATER_MARK: snapshot.high_water_mark,
    }.get(evidence_field)


class LiveRiskEvidenceAuthority:
    """Application-owned authority that binds and seals LIVE risk evidence.

    The authority is constructed by the sanctioned composition root with the
    exact expected account, broker connection, broker client id and transport.
    It calls the wired source, verifies every provenance dimension, stamps the
    capture instant from the trusted clock, and mints a per-instance HMAC seal.
    No caller-built dataclass or arbitrary callback can mint that seal.
    """

    def __init__(
        self,
        *,
        source: LiveRiskEvidenceSource,
        limits: RiskLimits,
        clock: Clock,
        account_id: AccountId,
        broker_connection_id: BrokerConnectionId,
        expected_broker_client_id: str,
        expected_transport: object,
    ) -> None:
        if not isinstance(source, LiveRiskEvidenceSource):
            raise TypeError("LIVE risk evidence authority requires a LiveRiskEvidenceSource")
        if not isinstance(clock, Clock):
            raise TypeError("LIVE risk evidence authority requires a Clock")
        if type(account_id) is not AccountId:
            raise TypeError("LIVE risk evidence authority requires an AccountId")
        if type(broker_connection_id) is not BrokerConnectionId:
            raise TypeError("LIVE risk evidence authority requires a BrokerConnectionId")
        if type(expected_broker_client_id) is not str or not expected_broker_client_id.strip():
            raise TypeError("LIVE risk evidence authority requires a broker client id")
        if expected_transport is None:
            raise TypeError("LIVE risk evidence authority requires the exact transport")
        self._source = source
        self._clock = clock
        self._account_id = account_id
        self._broker_connection_id = broker_connection_id
        self._broker_client_id = expected_broker_client_id
        self._transport = expected_transport
        self._limits = require_live_risk_limits(limits)
        max_snapshot_age = self._limits.max_snapshot_age
        if max_snapshot_age is None:  # pragma: no cover - require_live_risk_limits guarantees it
            raise TypeError("LIVE risk evidence authority requires a maximum snapshot age")
        self._max_snapshot_age = max_snapshot_age
        self._required_fields = required_live_risk_evidence_fields(self._limits)
        self._key = secrets.token_bytes(32)

    @property
    def required_fields(self) -> frozenset[LiveRiskEvidenceField]:
        return self._required_fields

    @property
    def authoritative_evidence_available(self) -> bool:
        """True only when the wired source declares every required field."""
        return self._required_fields <= self._source.supported_fields

    def admit(
        self, request: ApprovedExecutionRequest
    ) -> tuple[LiveRiskEvaluationInputs, LiveRiskEvidenceAuthorization] | RiskResult:
        """Collect, verify, stamp and seal one request's evidence, or reject."""
        if not self.authoritative_evidence_available:
            return RiskResult(RiskDecision.REJECT, _SOURCE_UNAVAILABLE_REASON)
        try:
            evidence = self._source.collect(request)
        except Exception:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_UNAVAILABLE_REASON)
        if type(evidence) is not LiveRiskEvidence:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_UNAVAILABLE_REASON)

        identity_reason = self._identity_reason(evidence)
        if identity_reason is not None:
            return RiskResult(RiskDecision.REJECT, identity_reason)
        request_reason = self._request_reason(request, evidence)
        if request_reason is not None:
            return RiskResult(RiskDecision.REJECT, request_reason)

        contradiction_reason = self._contradiction_reason(evidence)
        if contradiction_reason is not None:
            return RiskResult(RiskDecision.REJECT, contradiction_reason)

        completeness_reason, oldest = self._completeness_reason(evidence)
        if completeness_reason is not None:
            return RiskResult(RiskDecision.REJECT, completeness_reason)

        try:
            reading = self._clock.now()
        except Exception:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_CLOCK_UNAVAILABLE_REASON)
        captured_at = _utc_instant(reading)
        if captured_at is None:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_CLOCK_INVALID_REASON)

        instants = [observation.observed_at for observation in evidence.observations.values()]
        if evidence.identity_observed_at is not None:
            instants.append(evidence.identity_observed_at)
        if any(_utc_instant(instant) is None for instant in instants):
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_INCOMPLETE_REASON)
        safe_instants = [_utc_instant(instant) for instant in instants]
        if any(instant is not None and instant > captured_at for instant in safe_instants):
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_FUTURE_REASON)
        oldest = min(instant for instant in safe_instants if instant is not None)
        if captured_at - oldest > self._max_snapshot_age:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_STALE_REASON)

        context = evidence.context
        snapshot = evidence.snapshot
        if context is None or snapshot is None:  # pragma: no cover - completeness guarded
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_INCOMPLETE_REASON)
        intent = _intent_for_request(request)
        if intent is None:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_REQUEST_REASON)
        stamped = replace(snapshot, observed_at=oldest)
        inputs = LiveRiskEvaluationInputs(
            intent=intent,
            context=context,
            snapshot=stamped,
            claimed_evaluated_at=captured_at,
        )
        if not _risk_inputs_match_request(request, inputs):
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_REQUEST_REASON)
        return inputs, self._authorize(request, inputs)

    def verify(
        self,
        authorization: LiveRiskEvidenceAuthorization,
        request: ApprovedExecutionRequest,
        inputs: LiveRiskEvaluationInputs,
    ) -> bool:
        """Prove the authorization was minted by this authority for these inputs."""
        if type(authorization) is not LiveRiskEvidenceAuthorization:
            return False
        if type(authorization.client_order_id) is not UUID:
            return False
        if authorization.client_order_id != request.order.client_order_id:
            return False
        digest = _inputs_digest(request.order.client_order_id, inputs)
        if not hmac.compare_digest(authorization.evidence_digest, digest):
            return False
        expected_seal = self._seal(request.order.client_order_id, digest)
        return hmac.compare_digest(authorization.seal, expected_seal)

    def _identity_reason(self, evidence: LiveRiskEvidence) -> str | None:
        if type(evidence.source_id) is not str or evidence.source_id != self._source.source_id:
            return _EVIDENCE_IDENTITY_REASON
        if evidence.broker_client_id != self._broker_client_id:
            return _EVIDENCE_IDENTITY_REASON
        if evidence.account_id != self._account_id:
            return _EVIDENCE_IDENTITY_REASON
        if evidence.broker_connection_id != self._broker_connection_id:
            return _EVIDENCE_IDENTITY_REASON
        if evidence.transport is not self._transport:
            return _EVIDENCE_IDENTITY_REASON
        if evidence.identity_observed_at is None:
            return _EVIDENCE_INCOMPLETE_REASON
        if _utc_instant(evidence.identity_observed_at) is None:
            return _EVIDENCE_INCOMPLETE_REASON
        if evidence.context is None or evidence.snapshot is None:
            return _EVIDENCE_INCOMPLETE_REASON
        context = evidence.context
        snapshot = evidence.snapshot
        if type(context) is not RiskContext or type(snapshot) is not RiskSnapshot:
            return _EVIDENCE_IDENTITY_REASON
        if (
            context.account_id != self._account_id
            or context.broker_connection_id != self._broker_connection_id
            or snapshot.account_id != self._account_id
            or snapshot.broker_connection_id != self._broker_connection_id
            or context.financial_state.capital_source is not CapitalSourceType.LIVE_BROKER
            or context.instrument.market.region is not MarketRegion.INDIA
            or context.instrument.currency != context.financial_state.cash_balance.currency
        ):
            return _EVIDENCE_IDENTITY_REASON
        return None

    def _request_reason(
        self, request: ApprovedExecutionRequest, evidence: LiveRiskEvidence
    ) -> str | None:
        context = evidence.context
        snapshot = evidence.snapshot
        if context is None or snapshot is None:
            return _EVIDENCE_INCOMPLETE_REASON
        execution = request.execution_context
        if (
            context.portfolio_id != execution.portfolio_id
            or snapshot.portfolio_id != execution.portfolio_id
            or context.instrument.instrument_id != request.order.instrument
            or context.instrument.market != execution.market
            or context.product != request.product
            or context.effective_position_effect != request.effective_position_effect
            or context.market_pack_id != execution.market_pack_id
            or context.rule_version != execution.rule_version
            or not _same_instrument_resolution(
                context.instrument_resolution, request.instrument_resolution
            )
            or context.reference_price != _expected_reference_price(request)
            or snapshot.required_margin != request.required_margin
            or snapshot.available_margin != context.financial_state.margin_available.amount
        ):
            return _EVIDENCE_REQUEST_REASON
        return None

    def _contradiction_reason(self, evidence: LiveRiskEvidence) -> str | None:
        if evidence.contradictions:
            return _EVIDENCE_CONTRADICTION_REASON
        return None

    def _completeness_reason(self, evidence: LiveRiskEvidence) -> tuple[str | None, datetime]:
        context = evidence.context
        snapshot = evidence.snapshot
        if context is None or snapshot is None:
            return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
        unavailable = set(evidence.unavailable_fields)
        if unavailable & self._required_fields:
            return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
        observations = evidence.observations
        oldest = evidence.identity_observed_at
        if oldest is None:
            return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
        for evidence_field in self._required_fields:
            observation = observations.get(evidence_field)
            if type(observation) is not LiveRiskEvidenceObservation:
                return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
            if (
                type(observation.value) is not Decimal
                or not observation.value.is_finite()
                or _utc_instant(observation.observed_at) is None
            ):
                return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
            expected = _financial_expected(context, evidence_field)
            if expected is None:
                expected = _snapshot_expected(snapshot, evidence_field)
            if expected is None:
                return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
            if observation.value != expected:
                return _EVIDENCE_CONTRADICTION_REASON, datetime.min.replace(tzinfo=UTC)
            if observation.observed_at < oldest:
                oldest = observation.observed_at
        for observation in observations.values():
            if type(observation) is not LiveRiskEvidenceObservation:
                return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
            if _utc_instant(observation.observed_at) is None:
                return _EVIDENCE_INCOMPLETE_REASON, datetime.min.replace(tzinfo=UTC)
            if observation.observed_at < oldest:
                oldest = observation.observed_at
        return None, oldest

    def _seal(self, client_order_id: UUID, digest: str) -> str:
        message = f"{client_order_id}\x00{digest}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def _authorize(
        self,
        request: ApprovedExecutionRequest,
        inputs: LiveRiskEvaluationInputs,
    ) -> LiveRiskEvidenceAuthorization:
        client_order_id = request.order.client_order_id
        digest = _inputs_digest(client_order_id, inputs)
        return LiveRiskEvidenceAuthorization(
            client_order_id=client_order_id,
            evidence_digest=digest,
            seal=self._seal(client_order_id, digest),
        )


class LivePreTradeRiskEvaluator:
    """Callable LIVE risk evaluator bound to one trusted clock.

    The provider's timestamp is a claim to validate, not time authority: each
    evaluation reads the injected clock exactly once, and only that reading
    reaches the deterministic domain engine.
    """

    def __init__(
        self,
        *,
        engine: PreTradeRiskEngine,
        limits: RiskLimits,
        clock: Clock,
        inputs_for_request: (
            Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs] | None
        ) = None,
        authority: LiveRiskEvidenceAuthority | None = None,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("LIVE risk evaluator requires a Clock")
        if (inputs_for_request is None) == (authority is None):
            raise TypeError(
                "LIVE risk evaluator requires exactly one of inputs_for_request or authority"
            )
        if inputs_for_request is not None and not callable(inputs_for_request):
            raise TypeError("risk_inputs_for_request must be callable")
        if authority is not None and type(authority) is not LiveRiskEvidenceAuthority:
            raise TypeError("LIVE risk evaluator authority has an unsupported type")
        self._engine = engine
        self._limits = require_live_risk_limits(limits)
        self._inputs_for_request = inputs_for_request
        self._authority = authority
        self._clock = clock

    @property
    def authoritative_evidence_available(self) -> bool:
        """Whether an implemented authority can satisfy every required field.

        Callback mode is always non-authoritative: type-correct dataclasses and
        trusted-clock freshness do not authenticate balances, positions, P&L,
        account, connection, transport, client identity, or observation-time
        provenance. Authority mode is available only when its wired source
        declares every field the configured limits require.
        """
        if self._authority is None:
            return False
        return self._authority.authoritative_evidence_available

    def __call__(self, request: ApprovedExecutionRequest) -> RiskResult:
        if self._authority is not None:
            return self._evaluate_with_authority(request)
        return self._evaluate_with_callback(request)

    def _evaluate_with_authority(self, request: ApprovedExecutionRequest) -> RiskResult:
        authority = self._authority
        if authority is None:  # pragma: no cover - branch guarded by __call__
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_UNAVAILABLE_REASON)
        admission = authority.admit(request)
        if type(admission) is RiskResult:
            return admission
        if type(admission) is not tuple or len(admission) != 2:
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_UNAVAILABLE_REASON)
        inputs, authorization = admission
        if type(inputs) is not LiveRiskEvaluationInputs or not authority.verify(
            authorization, request, inputs
        ):
            return RiskResult(RiskDecision.REJECT, _EVIDENCE_AUTHORIZATION_REASON)
        if not _risk_inputs_match_request(request, inputs):
            return _reject(inputs, _REQUEST_MISMATCH_REASON)
        try:
            reading = self._clock.now()
        except Exception:
            return _reject(inputs, _CLOCK_UNAVAILABLE_REASON)
        trusted = _utc_instant(reading)
        if trusted is None:
            return _reject(inputs, _CLOCK_INVALID_REASON)
        claim = _utc_instant(inputs.claimed_evaluated_at)
        if claim is None:
            return _reject(inputs, _CLAIM_INVALID_REASON)
        if abs(trusted - claim) > _MAX_LIVE_RISK_CLOCK_SKEW:
            return _reject(inputs, _CLAIM_OUT_OF_TOLERANCE_REASON)
        return self._engine.evaluate_with_limits(
            inputs.intent,
            inputs.context,
            limits=self._limits,
            snapshot=inputs.snapshot,
            evaluated_at=trusted,
        )

    def _evaluate_with_callback(self, request: ApprovedExecutionRequest) -> RiskResult:
        inputs_for_request = self._inputs_for_request
        if inputs_for_request is None:  # pragma: no cover - branch guarded by __call__
            raise TypeError("LIVE risk evaluation inputs provider is unavailable")
        inputs = inputs_for_request(request)
        if type(inputs) is not LiveRiskEvaluationInputs:
            raise TypeError("LIVE risk evaluation inputs have an unsupported type")
        if not _risk_inputs_match_request(request, inputs):
            return _reject(inputs, _REQUEST_MISMATCH_REASON)
        try:
            reading = self._clock.now()
        except Exception:
            return _reject(inputs, _CLOCK_UNAVAILABLE_REASON)
        trusted = _utc_instant(reading)
        if trusted is None:
            return _reject(inputs, _CLOCK_INVALID_REASON)
        claim = _utc_instant(inputs.claimed_evaluated_at)
        if claim is None:
            return _reject(inputs, _CLAIM_INVALID_REASON)
        if abs(trusted - claim) > _MAX_LIVE_RISK_CLOCK_SKEW:
            return _reject(inputs, _CLAIM_OUT_OF_TOLERANCE_REASON)
        return self._engine.evaluate_with_limits(
            inputs.intent,
            inputs.context,
            limits=self._limits,
            snapshot=inputs.snapshot,
            evaluated_at=trusted,
        )
