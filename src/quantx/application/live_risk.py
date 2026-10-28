"""Validated LIVE pre-trade risk evaluator composition.

The provider supplies risk evidence and a timestamp claim. The evaluator reads
one trusted clock and passes only that reading to the deterministic domain
engine as the evaluation instant. This prevents a provider from making an
already-old ``snapshot.observed_at`` pass freshness merely by claiming a recent
evaluation time: the engine computes the snapshot age from the trusted instant
against the provider-supplied observation instant. This slice does not
authenticate the accuracy or provenance of ``snapshot.observed_at``, so a
fabricated observation instant is not detected here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from quantx.domain.clock import Clock
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.finance import CapitalSourceType
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


def _same_instrument_resolution(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return left.identity_payload() == right.identity_payload()  # type: ignore[attr-defined]
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
        or intent.strategy_id != order.strategy_id
        or intent.strategy_version != order.strategy_version
        or intent.product != request.product
        or intent.product != order.product
        or intent.position_effect != request.position_effect
        or intent.position_effect != order.position_effect
        or intent.execution_context != request.execution_context
        or context.instrument.instrument_id != order.instrument
        or context.instrument.market != request.execution_context.market
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
        inputs_for_request: Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs],
        clock: Clock,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("LIVE risk evaluator requires a Clock")
        self._engine = engine
        self._limits = require_live_risk_limits(limits)
        self._inputs_for_request = inputs_for_request
        self._clock = clock

    @property
    def authoritative_evidence_available(self) -> bool:
        """Whether inputs are authenticated by an implemented trusted source.

        The current composition accepts a caller-controlled callback returning
        dataclasses. Type-correct inputs and trusted-clock freshness do not
        authenticate snapshot, position, balance, P&L, account, connection, or
        observation-time provenance. Until a concrete authority-bearing source
        is implemented, LIVE must remain unavailable.
        """
        return False

    def __call__(self, request: ApprovedExecutionRequest) -> RiskResult:
        inputs = self._inputs_for_request(request)
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
